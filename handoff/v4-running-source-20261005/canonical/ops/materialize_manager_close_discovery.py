"""One-shot research materializer invoked by the existing hourly owner.

1500 may prepare its original membership dependency; only 1530 captures quotes.

No scheduler, subscription, second quote feed or GET side effect is defined.
Data/universe remain in V35; output MUST bind to the V4 API's manager state.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, time, timedelta
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import tempfile
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

APP_ROOT=Path(__file__).resolve().parents[1]
for _path in (APP_ROOT/'upstreams',APP_ROOT/'upstreams'/'v3_shared_data'):
    if str(_path) not in sys.path: sys.path.insert(0,str(_path))

from apps.api.v35_api.manager_workbench_router import validate_workbench_payload, _empty_envelope
from contracts.trading_calendar import load_market_calendar, resolve_market_states, previous_session, TradingDayState
from domains.manager_close_discovery import FOUR_FLAGS, RULE_VERSION as LEGACY_RULE_VERSION
from domains.manager_close_rebound import (RULE as RULE_VERSION, capture_history,
    read_history, require_authority_root, build_payload as build_workbench_payload)
from domains.manager_catalyst_tracking import read_catalyst_events, read_prior_evidence
from domains.manager_research_evidence import read_universe_evidence, persist_snapshot, read_snapshot_evidence, universe_at_snapshot, EvidenceError, load_universe_owner
from infrastructure.manager_input_attestation import encoded, digest, resolve, load, aware, atomic_create, PublicationError
from infrastructure.interprocess_lock import owned_interprocess_lock
from shared_data.hk_auction_0920 import fetch_futu_snapshot

HK=ZoneInfo('Asia/Hong_Kong')
RESULT_SCHEMA='v4.manager_close_materialization_result.v1'
CLOSE_RECAPTURE_SCHEMA='v4.manager_close_recapture.v1'
CLOSE_RECAPTURE_RESULT_SCHEMA='v4.manager_close_recapture_result.v1'
CLOSE_RECAPTURE_STAGE='STAGE_1545_1555'
CLOSE_RECAPTURE_FLAGS={'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}


def _clock() -> datetime: return datetime.now(HK)


def _root(value: Path | None, code: str) -> Path:
    if value is None or not Path(value).expanduser().is_absolute(): raise EvidenceError(code)
    return Path(value).expanduser().resolve()


def _futu_executable_path(value: Path | None, *, owner_sha256: str) -> Path:
    """Normalize the configured interpreter without following venv symlinks."""
    context = dict(layer='UNIVERSE_OWNER', field='futu_python', owner_sha256=owner_sha256)
    try:
        if value is None:
            raise ValueError('missing interpreter path')
        configured = Path(value).expanduser()
        if not configured.is_absolute():
            raise ValueError('interpreter path must be absolute')
        executable = Path(os.path.abspath(os.fspath(configured)))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise EvidenceError('EXISTING_FUTU_PYTHON_REQUIRED', kind='INVALID', **context) from exc
    if not executable.exists() or not executable.is_file():
        raise EvidenceError('EXISTING_FUTU_PYTHON_MISSING', kind='MISSING', **context)
    if not os.access(executable, os.X_OK):
        raise EvidenceError('EXISTING_FUTU_PYTHON_NOT_EXECUTABLE', kind='INVALID', **context)
    return executable


def _status(root: Path, date: str, status: str, reason: str, at: datetime, *, diagnostic: dict | None = None) -> None:
    from infrastructure.manager_close_attempt import write_attempt
    write_attempt(root,date,status,reason,at,diagnostic=diagnostic)


def _result(date: str,status: str,reason: str | None=None,**values: Any) -> dict:
    return {'schema_version':RESULT_SCHEMA,'status':status,'trade_date':date,'slot':'1530',
            'reason':reason,'module_origin':str(Path(__file__).resolve()),
            'module_sha256':digest(Path(__file__).read_bytes()),**values,**FOUR_FLAGS}


def _close_recapture_result(date: str,status: str,reason: str | None=None, *, plan_trade_date: str | None=None, **values: Any) -> dict:
    return {'schema_version':CLOSE_RECAPTURE_RESULT_SCHEMA,'status':status,
            'source_trade_date':date,'plan_trade_date':plan_trade_date,
            'capture_mode':'LATE_OBSERVATION','reason':reason,
            'module_origin':str(Path(__file__).resolve()),
            'module_sha256':digest(Path(__file__).read_bytes()),**values,**CLOSE_RECAPTURE_FLAGS}


def _read_close_recapture_pool(store_root: Path, trade_date: str) -> tuple[dict,list[dict]]:
    """Read the one exact-date HK Connect D1 Top100 owner publication."""
    run_root=resolve(store_root,f'runs/{trade_date}/HK_CONNECT_D1_TOP100_0_2')
    manifests=sorted(run_root.glob('*/manifest.json'))
    if len(manifests)!=1:
        raise EvidenceError('CLOSE_RECAPTURE_EXACT_POOL_NOT_UNIQUE',layer='POOL_OWNER',kind='MISSING' if not manifests else 'CONFLICT')
    manifest_path=manifests[0]
    manifest=load(manifest_path)
    run_dir=manifest_path.parent
    receipt=load(resolve(store_root,f'{run_dir.relative_to(store_root).as_posix()}/receipt.json'))
    relative=str(manifest.get('artifact_relative') or '')
    artifact_path=resolve(store_root,relative)
    artifact_raw=artifact_path.read_bytes()
    artifact_sha=digest(artifact_raw)
    manifest_raw=manifest_path.read_bytes()
    manifest_sha=digest(manifest_raw)
    receipt_sha=digest(resolve(store_root,f'{run_dir.relative_to(store_root).as_posix()}/receipt.json').read_bytes())
    run_id=str(receipt.get('run_id') or '')
    if (manifest.get('schema_version')!='v3_shared_data.manifest.v1'
            or manifest.get('market')!='HK_CONNECT' or manifest.get('stage_id')!='D1_PREMARKET'
            or manifest.get('trade_date')!=trade_date or manifest.get('row_count')!=100
            or manifest.get('source_id')!='hkconnect_0_2_frozen_prob_active'
            or manifest.get('provenance',{}).get('source_contract')!='tdx_vipdoc_71_day_prob_active'
            or receipt.get('schema_version')!='v3_shared_data.receipt.v1'
            or receipt.get('status')!='READY' or receipt.get('owner')!='v3_shared_data'
            or receipt.get('role')!='HK_CONNECT_D1_TOP100_0_2' or receipt.get('trade_date')!=trade_date
            or receipt.get('run_id')!=run_dir.name or run_id!=run_dir.name
            or receipt.get('artifact_sha256')!=artifact_sha
            or manifest.get('artifact_sha256')!=artifact_sha
            or receipt.get('manifest_sha256')!=manifest_sha
            or any(receipt.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent'))):
        raise EvidenceError('CLOSE_RECAPTURE_POOL_OWNER_CONTRACT_INVALID',layer='POOL_OWNER',kind='INVALID')
    try:
        signal_date=str(manifest.get('signal_date') or '')
        pool_captured=aware(manifest.get('captured_at'))
    except PublicationError as exc:
        raise EvidenceError('CLOSE_RECAPTURE_POOL_TIME_INVALID',layer='POOL_OWNER',kind='INVALID') from exc
    if pool_captured.strftime('%Y%m%d')>trade_date or not re.fullmatch(r'\d{8}',signal_date):
        raise EvidenceError('CLOSE_RECAPTURE_POOL_TEMPORAL_CONTRACT_INVALID',layer='POOL_OWNER',kind='INVALID')
    rows=[]; seen=set()
    try:
        import io
        reader=csv.DictReader(io.StringIO(artifact_raw.decode('utf-8-sig')))
        for raw in reader:
            code=str(raw.get('code') or '').strip().upper()
            rank=int(raw.get('rank'))
            if (not re.fullmatch(r'HK\.\d{5}',code) or code in seen or rank!=len(rows)+1
                    or raw.get('target_date')!=trade_date or raw.get('signal_date')!=signal_date
                    or raw.get('recommendation_status')!='WATCH_ONLY_BACKTEST_GATED'
                    or raw.get('production_allowed','').casefold()!='false'):
                raise ValueError('row contract')
            seen.add(code)
            try: score=float(raw.get('score_prob_active'))
            except (TypeError,ValueError): score=None
            rows.append({'symbol':code,'name':str(raw.get('name') or code),'pool_rank':rank,
                         'pool_score':score,'signal_date':signal_date,'target_date':trade_date})
    except (UnicodeError,ValueError,TypeError,csv.Error) as exc:
        raise EvidenceError('CLOSE_RECAPTURE_POOL_ROWS_INVALID',layer='POOL_OWNER',kind='INVALID') from exc
    if len(rows)!=100 or len(seen)!=100:
        raise EvidenceError('CLOSE_RECAPTURE_POOL_COUNT_INVALID',layer='POOL_OWNER',kind='INVALID')
    identity={'owner':'v3_shared_data','role':'HK_CONNECT_D1_TOP100_0_2','trade_date':trade_date,
        'signal_date':signal_date,'source_id':manifest['source_id'],'run_id':run_id,
        'artifact_ref':relative,'artifact_sha256':artifact_sha,
        'manifest_ref':f'{run_dir.relative_to(store_root).as_posix()}/manifest.json',
        'manifest_sha256':manifest_sha,'receipt_ref':f'{run_dir.relative_to(store_root).as_posix()}/receipt.json',
        'receipt_sha256':receipt_sha,'captured_at':manifest['captured_at'],'row_count':len(rows)}
    return identity,rows


def _pytdx_source_identity(source_root: Path) -> dict:
    files={'provider':'scripts/live_acquisition/pytdx_exhq.py',
           'probe':'scripts/live_acquisition/pytdx_exhq_probe.py',
           'contracts':'scripts/live_acquisition/contracts.py',
           'aggregator':'scripts/live_acquisition/futu_minute.py'}
    output={}
    for key,relative in files.items():
        path=resolve(source_root,relative)
        output[key]={'artifact_ref':relative,'sha256':digest(path.read_bytes())}
    return output


def _next_hk_session(calendar: Any, source_date: str) -> str:
    cursor=datetime.strptime(source_date,'%Y%m%d').date()+timedelta(days=1)
    for _ in range(15):
        token=cursor.strftime('%Y%m%d')
        try: state=resolve_market_states(calendar,token)['hk_connect']
        except ValueError: break
        if state in {TradingDayState.FULL_TRADING_DAY,TradingDayState.HALF_TRADING_DAY_AM}:
            return token
        cursor+=timedelta(days=1)
    raise EvidenceError('CLOSE_RECAPTURE_NEXT_HK_SESSION_UNAVAILABLE',layer='CONFIGURATION',kind='INVALID')


def _normalized_pytdx_observations(rows: Sequence[Mapping[str,Any]], pool_rows: Sequence[Mapping[str,Any]],
                                   *, trade_date: str, captured_at: datetime) -> list[dict]:
    pool={row['symbol']:row for row in pool_rows}
    output=[]; seen=set()
    for raw in rows:
        if not isinstance(raw,Mapping): continue
        symbol=str(raw.get('code') or '').strip().upper()
        member=pool.get(symbol)
        if member is None or symbol in seen: continue
        raw_time=raw.get('update_time')
        if not isinstance(raw_time,str): continue
        try: observed=datetime.strptime(raw_time,'%Y-%m-%d %H:%M:%S').replace(tzinfo=HK)
        except ValueError: continue
        if (observed.strftime('%Y%m%d')!=trade_date or observed.time()<time(15,46)
                or observed.time()>=time(15,55,5) or observed>captured_at.astimezone(HK)):
            continue
        seen.add(symbol)
        output.append({'symbol':symbol,'name':member['name'],'pool_rank':member['pool_rank'],
            'pool_score':member['pool_score'],'source_trade_date':trade_date,
            'observed_at':observed.isoformat(timespec='seconds'),'available_at':captured_at.isoformat(timespec='microseconds'),
            'open_price':raw.get('open_price'),'high_price':raw.get('high_price'),
            'low_price':raw.get('low_price'),'last_price':raw.get('last_price'),
            'prev_close_price':raw.get('prev_close_price'),'volume':raw.get('volume'),
            'turnover':raw.get('turnover'),'turnover_currency':'UNKNOWN','turnover_unit':'UNKNOWN',
            'bar_count':raw.get('bar_count'),'window_start':raw.get('window_start'),
            'window_end':raw.get('window_end'),'candidate_status':'OBSERVATION_ONLY'})
    return sorted(output,key=lambda row:row['pool_rank'])


def recapture_close_minutes(*, manager_state_root: Path, universe_root: Path, pytdx_python: Path,
                            trade_date: str, app_root: Path=APP_ROOT,
                            provider_root: Path | None=None, clock: Callable[[],datetime]=_clock,
                            pytdx_collector: Callable[...,Any] | None=None,
                            process_runner: Callable[...,Any] | None=None) -> dict:
    """Explicit late-mode read of the existing HK PyTDX ExHQ minute owner.

    This never calls Futu and never writes the historical 1530 lane. It captures
    the existing 15:45-15:55 source window over the immutable exact-date D1 pool.
    """
    state=_root(manager_state_root,'V4_MANAGER_STATE_ROOT_REQUIRED')
    universe=_root(universe_root,'V35_UNIVERSE_ROOT_REQUIRED')
    if _root(app_root,'V4_APP_ROOT_REQUIRED')!=APP_ROOT:
        raise EvidenceError('V4_IMPORT_ORIGIN_MISMATCH')
    now=clock()
    if now.tzinfo is None: raise EvidenceError('CLOCK_MUST_BE_AWARE')
    now=now.astimezone(HK)
    today=now.strftime('%Y%m%d')
    if trade_date>today:
        raise EvidenceError('LATE_RECAPTURE_SOURCE_DATE_IN_FUTURE')
    if trade_date==today and now.time()<time(15,55,5):
        raise EvidenceError('PYTDX_STAGE_WINDOW_NOT_COMPLETE',layer='CAPTURE_WINDOW',kind='EXPIRED')
    try:
        calendar=load_market_calendar()
        market=resolve_market_states(calendar,trade_date)['hk_connect']
    except (ValueError,OSError) as exc:
        raise EvidenceError('TRADING_CALENDAR_UNVERIFIED') from exc
    if market is not TradingDayState.FULL_TRADING_DAY:
        return _close_recapture_result(trade_date,'NOT_APPLICABLE','NO_HK_CONNECT_FULL_SESSION',state_root=str(state))
    try:
        latest_closed_session=previous_session(calendar,today,market='hk_connect')
    except ValueError:
        latest_closed_session=''
    if trade_date not in {today,latest_closed_session}:
        raise EvidenceError('LATE_RECAPTURE_SOURCE_NOT_CURRENT_OR_PREVIOUS_SESSION',layer='CONFIGURATION',kind='INVALID')
    plan_date=_next_hk_session(calendar,trade_date)
    artifact_ref=f'workbench_research/{trade_date}/close_recapture.json'
    artifact_path=resolve(state,artifact_ref)
    receipt_path=resolve(state,f'workbench_research/{trade_date}/close_recapture.receipt.json')
    lock=resolve(state,f'workbench_research/{trade_date}/close_recapture.lock')
    try:
        with owned_interprocess_lock(lock,timeout_seconds=0,timeout_message='CLOSE_RECAPTURE_SLOT_LOCKED',timeout_error=EvidenceError):
            if artifact_path.is_file():
                raw=artifact_path.read_bytes(); value=load(artifact_path)
                receipt=load(receipt_path)
                if (receipt.get('artifact_sha256')!=digest(raw) or value.get('schema_version')!=CLOSE_RECAPTURE_SCHEMA
                        or value.get('source_trade_date')!=trade_date):
                    raise EvidenceError('CLOSE_RECAPTURE_EXISTING_PRODUCT_CONFLICT',layer='PUBLICATION',kind='CONFLICT')
                return _close_recapture_result(trade_date,'ALREADY_EXISTS',plan_trade_date=value.get('plan_trade_date'),artifact_ref=artifact_ref,
                    artifact_sha256=digest(raw),candidate_count=value.get('candidate_overlay',{}).get('count'),
                    state_root=str(state))
            store_root=_root(universe/'.runtime/data','V35_SHARED_DATA_STORE_ROOT_REQUIRED')
            pool,pool_rows=_read_close_recapture_pool(store_root,trade_date)
            python=Path(pytdx_python).expanduser()
            if not python.is_absolute() or not python.is_file() or not os.access(python,os.X_OK):
                raise EvidenceError('PYTDX_HK_RUNTIME_REQUIRED',layer='CONFIGURATION',kind='INVALID')
            source_root=_root(provider_root or Path(os.environ.get('V35_SHARED_PACKAGE_ROOT') or APP_ROOT/'upstreams/v3_shared_data'),
                              'PYTDX_SHARED_SOURCE_ROOT_REQUIRED')
            source_identity=_pytdx_source_identity(source_root)
            from scripts.live_acquisition.pytdx_exhq import collect_pytdx_exhq_minute
            if pytdx_collector is None: pytdx_collector=collect_pytdx_exhq_minute
            if process_runner is None:
                def process_runner(command, **kwargs):
                    env=os.environ.copy()
                    env['PYTHONPATH']=str(source_root)+((os.pathsep+env['PYTHONPATH']) if env.get('PYTHONPATH') else '')
                    env['PYTHONDONTWRITEBYTECODE']='1'
                    return subprocess.run(command,env=env,**kwargs)
            started=clock().astimezone(HK)
            result=pytdx_collector(python,trade_date,CLOSE_RECAPTURE_STAGE,
                [row['symbol'] for row in pool_rows],market='HK_CONNECT',
                process_runner=process_runner,timeout_seconds=360)
            captured=clock().astimezone(HK)
            if captured.strftime('%Y%m%d')>today or captured.strftime('%Y%m%d')<trade_date or captured<started:
                raise EvidenceError('CLOSE_RECAPTURE_CAPTURE_TIME_INVALID',layer='CAPTURE_WINDOW',kind='INVALID')
            observations=_normalized_pytdx_observations(getattr(result,'rows',[]),pool_rows,
                trade_date=trade_date,captured_at=captured)
            if not observations:
                status_ref=f'workbench_research/{trade_date}/close_recapture.status.json'
                failure={'schema_version':CLOSE_RECAPTURE_SCHEMA,'status':'FAILED','source_trade_date':trade_date,
                    'target_trade_date':plan_date,'plan_trade_date':plan_date,
                    'capture_mode':'LATE_OBSERVATION','observation_type':'PYTDX_EXHQ_MINUTE_STAGE_OBSERVATION',
                    'reason':'PYTDX_CAPTURE_RETURNED_NO_VALID_OBSERVATIONS','request':{'started_at':started.isoformat(),
                    'captured_at':captured.isoformat()},'pool':pool,'source':{'provider':'pytdx_exhq','source_id':'pytdx'},
                    'coverage':{'eligible_count':100,'requested_count':getattr(result,'requested_code_count',0),
                        'completed_count':getattr(result,'completed_code_count',0),'observed_count':0,
                        'no_data_count':len(getattr(result,'no_data_codes',[]) or []),'ratio':0.0},
                    'cannot_confirm':['PYTDX_EXHQ_NONEMPTY_OBSERVATION_REQUIRED'],**CLOSE_RECAPTURE_FLAGS}
                status_path=resolve(state,status_ref); status_raw=encoded(failure)
                if not atomic_create(status_path,status_raw) and status_path.read_bytes()!=status_raw:
                    raise EvidenceError('CLOSE_RECAPTURE_STATUS_CONFLICT',layer='PUBLICATION',kind='CONFLICT')
                return _close_recapture_result(trade_date,'FAILED',failure['reason'],plan_trade_date=plan_date,artifact_ref=status_ref,
                    artifact_sha256=digest(status_raw),coverage=failure['coverage'],state_root=str(state))
            output_root=f'workbench_research/{trade_date}'
            snapshot_ref=f'{output_root}/inputs/close_recapture_pytdx.json'
            candidates_ref=f'{output_root}/close_recapture.candidates.json'
            no_data=list(getattr(result,'no_data_codes',[]) or [])
            missing=100-len(observations)
            status='READY' if len(observations)==100 and getattr(result,'status',None)=='READ_OK' else 'PARTIAL'
            cannot=[]
            if missing: cannot.append('PYTDX_EXHQ_COVERAGE_INCOMPLETE')
            cannot.extend(['MARKET_CLOSE_NOT_CAPTURED_STAGE_WINDOW_ENDS_15_55_05',
                           'PYTDX_TURNOVER_CURRENCY_UNIT_UNVERIFIED'])
            raw_capture={'schema_version':'v4.manager_close_recapture_pytdx_snapshot.v1',
                'source_trade_date':trade_date,'stage_id':CLOSE_RECAPTURE_STAGE,'market':'HK_CONNECT',
                'pool':pool,'source':{'provider':'pytdx_exhq','source_id':'pytdx','source_identity':source_identity},
                'request':{'started_at':started.isoformat(timespec='microseconds'),
                    'captured_at':captured.isoformat(timespec='microseconds')},
                'coverage':{'eligible_count':100,'requested_count':getattr(result,'requested_code_count',0),
                    'completed_count':getattr(result,'completed_code_count',0),'observed_count':len(observations),
                    'no_data_count':len(no_data),'no_data_symbols':sorted(set(no_data)),
                    'ratio':len(observations)/100},
                'source_rows':list(getattr(result,'rows',[]) or []),**CLOSE_RECAPTURE_FLAGS}
            snapshot_raw=encoded(raw_capture)
            snapshot_path=resolve(state,snapshot_ref)
            if not atomic_create(snapshot_path,snapshot_raw) and snapshot_path.read_bytes()!=snapshot_raw:
                raise EvidenceError('CLOSE_RECAPTURE_SNAPSHOT_CONFLICT',layer='PUBLICATION',kind='CONFLICT')
            candidate_overlay={'schema_version':'v4.manager_close_recapture_candidate_overlay.v1',
                'source_trade_date':trade_date,'target_trade_date':plan_date,
                'source_pool':pool,'available_at':captured.isoformat(timespec='microseconds'),
                'rows':observations,**CLOSE_RECAPTURE_FLAGS}
            candidates_raw=encoded(candidate_overlay)
            candidates_path=resolve(state,candidates_ref)
            if not atomic_create(candidates_path,candidates_raw) and candidates_path.read_bytes()!=candidates_raw:
                raise EvidenceError('CLOSE_RECAPTURE_CANDIDATE_OVERLAY_CONFLICT',layer='PUBLICATION',kind='CONFLICT')
            observed_times=[aware(row['observed_at']) for row in observations]
            available=clock().astimezone(HK)
            if available<captured:
                raise EvidenceError('CLOSE_RECAPTURE_PUBLICATION_TIME_INVALID',layer='PUBLICATION',kind='INVALID')
            payload={'schema_version':CLOSE_RECAPTURE_SCHEMA,'status':status,
                'source_trade_date':trade_date,'target_trade_date':plan_date,'plan_trade_date':plan_date,'market':'HK_CONNECT',
                'capture_mode':'LATE_OBSERVATION','observation_type':'PYTDX_EXHQ_MINUTE_STAGE_OBSERVATION',
                'received_not_historical_1530':True,
                'bar_window':{'stage_id':CLOSE_RECAPTURE_STAGE,'start_at':'15:46:00','end_before':'15:55:05',
                    'window_semantics':'[STAGE_WINDOW_START+1min, STAGE_WINDOW_END)',
                    'observed_at_min':min(observed_times).isoformat(timespec='seconds'),
                    'observed_at_max':max(observed_times).isoformat(timespec='seconds')},
                'request':{'started_at':started.isoformat(timespec='microseconds'),
                    'captured_at':captured.isoformat(timespec='microseconds'),
                    'available_at':available.isoformat(timespec='microseconds')},
                'pool':pool,'source':{'provider':'pytdx_exhq','source_id':'pytdx',
                    'source_identity':source_identity},
                'coverage':raw_capture['coverage'],
                'snapshot':{'artifact_ref':snapshot_ref,'sha256':digest(snapshot_raw),
                    'row_count':len(raw_capture['source_rows'])},
                'candidate_overlay':{'artifact_ref':candidates_ref,'sha256':digest(candidates_raw),
                    'count':len(observations)},'cannot_confirm':sorted(set(cannot)),**CLOSE_RECAPTURE_FLAGS}
            payload_raw=encoded(payload)
            if not atomic_create(artifact_path,payload_raw) and artifact_path.read_bytes()!=payload_raw:
                raise EvidenceError('CLOSE_RECAPTURE_IMMUTABLE_CONFLICT',layer='PUBLICATION',kind='CONFLICT')
            receipt={'schema_version':'v4.manager_close_recapture_receipt.v1','status':status,
                'source_trade_date':trade_date,'target_trade_date':plan_date,
                'artifact_ref':artifact_ref,'artifact_sha256':digest(payload_raw),
                'snapshot_ref':snapshot_ref,'snapshot_sha256':digest(snapshot_raw),
                'candidate_overlay_ref':candidates_ref,'candidate_overlay_sha256':digest(candidates_raw),
                'captured_at':payload['request']['captured_at'],'available_at':payload['request']['available_at'],
                'candidate_count':len(observations),**CLOSE_RECAPTURE_FLAGS}
            receipt_raw=encoded(receipt)
            if not atomic_create(receipt_path,receipt_raw) and receipt_path.read_bytes()!=receipt_raw:
                raise EvidenceError('CLOSE_RECAPTURE_RECEIPT_CONFLICT',layer='PUBLICATION',kind='CONFLICT')
            result_status='MATERIALIZED' if status=='READY' else 'PARTIAL'
            return _close_recapture_result(trade_date,result_status,plan_trade_date=plan_date,artifact_ref=artifact_ref,
                artifact_sha256=digest(payload_raw),receipt_ref=f'{output_root}/close_recapture.receipt.json',
                receipt_sha256=digest(receipt_raw),snapshot_ref=snapshot_ref,snapshot_sha256=digest(snapshot_raw),
                candidate_overlay_ref=candidates_ref,candidate_overlay_sha256=digest(candidates_raw),
                candidate_count=len(observations),coverage=payload['coverage'],state_root=str(state))
    except EvidenceError as error:
        return _close_recapture_result(trade_date,'FAILED',str(error),failure_diagnostic=error.diagnostic,
            state_root=str(state))
    except (OSError,ValueError,TypeError,KeyError,ImportError,TimeoutError,subprocess.SubprocessError) as error:
        return _close_recapture_result(trade_date,'FAILED','PYTDX_CLOSE_RECAPTURE_FAILED',
            exception_type=type(error).__name__,state_root=str(state))


def _published_result(root: Path,date: str,status: str, *, rebound_authority_root: Path | None = None) -> dict | None:
    path=resolve(root,f'workbench_research/{date}/1530.json')
    if not path.is_file(): return None
    raw=path.read_bytes()
    decoded=json.loads(raw)
    if decoded.get('rule_version') == RULE_VERSION:
        try:
            rebound_authority_root = require_authority_root(rebound_authority_root)
        except (ValueError,OSError) as exc:
            code = str(exc) if str(exc).startswith('REBOUND_HISTORY_AUTHORITY_') else 'REBOUND_HISTORY_AUTHORITY_ROOT_INVALID'
            raise EvidenceError(code,layer='CONFIGURATION',kind='INVALID',field='rebound_authority_root') from exc
    value=validate_workbench_payload(decoded,expected_date=date,state_root=root,
        verify_published_sources=decoded.get('rule_version')==RULE_VERSION,
        rebound_authority_root=rebound_authority_root)
    if value['rule_version'] not in {RULE_VERSION,LEGACY_RULE_VERSION} or value['status'] not in {'READY','READY_EMPTY','PARTIAL'}:
        raise EvidenceError('EXISTING_WORKBENCH_VERSION_OR_STATUS_CONFLICT')
    receipt=_result(date,status,artifact_ref=f'workbench_research/{date}/1530.json',artifact_sha256=digest(raw),
        artifact_status=value['status'],run_id=value['run_id'],observation_count=len(value['candidates']),
        candidate_count=len(value['candidates']),qualified_count=sum(c['qualified'] is True for c in value['candidates']),
        state_root=str(root),condition_coverage='INCOMPLETE' if value['cannot_confirm'] else 'COMPLETE')
    if value['rule_version']==LEGACY_RULE_VERSION:
        return {**receipt,'status':'ALREADY_EXISTS','published_rule_version':LEGACY_RULE_VERSION}
    receipt.update(published_rule_version=RULE_VERSION,
        rebound_authority_binding=value['rebound_screen']['authority_binding'])
    # The result receipt is immutable; ALREADY_EXISTS describes this invocation,
    # whereas the persisted identity always describes the original publication.
    stored={**receipt,'status':'MATERIALIZED'}
    sidecar=resolve(root,f'workbench_research/{date}/1530.receipt.json')
    if not atomic_create(sidecar,encoded(stored)) and sidecar.read_bytes()!=encoded(stored):
        raise EvidenceError('WORKBENCH_RESULT_RECEIPT_CONFLICT')
    return receipt


def _news_paths(root: Path,date: str) -> tuple[list[Path],str | None]:
    calendar=load_market_calendar(); dates=[date]; cursor=date
    for _ in range(2):
        try: cursor=previous_session(calendar,cursor,market='hk_connect')
        except ValueError: break
        dates.insert(0,cursor)
    paths=[]
    for selected in dates:
        folder=resolve(root,f'research/incoming/{selected}')
        if not folder.is_dir(): continue
        for path in sorted(folder.glob('*.json')):
            if len(path.stem)==4 and path.stem.isdigit() and (selected!=date or path.stem<='1530'):
                paths.append(path)
    return paths,dates[-2] if len(dates)>1 else None



# Fixed adapter only: call the EXISTING owner in the EXISTING Futu interpreter.
# No quote implementation, membership reconstruction or new publication contract.
_OWNER_MARKER = "V4_ORIGINAL_HK_UNIVERSE_RESULT="
_OWNER_CALL = r"""
import contextlib, hashlib, importlib.util, json, os, pathlib, sys
marker = "V4_ORIGINAL_HK_UNIVERSE_RESULT="
p = pathlib.Path(sys.argv[1]); expected = sys.argv[2]
phase = 'OWNER_IMPORT'
allowed = {'RuntimeError','ValueError','TypeError','KeyError','ImportError','ModuleNotFoundError',
           'OSError','FileNotFoundError','PermissionError','TimeoutError','ConnectionError','AssertionError'}
def diagnostic(exc=None):
    causes=[]; frames=[]; seen=set()
    while exc is not None and len(causes)<3 and id(exc) not in seen:
        seen.add(id(exc)); name=type(exc).__name__
        causes.append({'type':name if name in allowed else 'OTHER'})
        tb=exc.__traceback__
        while tb is not None and len(frames)<8:
            if pathlib.Path(tb.tb_frame.f_code.co_filename)==p:
                frames.append({'file':'stage_center/hk_universe_preflight.py',
                               'function':tb.tb_frame.f_code.co_name,'line':tb.tb_lineno})
            tb=tb.tb_next
        exc=exc.__cause__ if exc.__cause__ is not None else (None if exc.__suppress_context__ else exc.__context__)
    return {'schema_version':'v4.manager_owner_failure.v1','owner_sha256':expected,
            'phase':phase,'causes':causes,'frames':frames}
try:
    with open(os.devnull,'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        if hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
            phase='OWNER_IDENTITY';raise ValueError('owner bytes mismatch')
        # Isolated (-I) mode ignores PYTHONDONTWRITEBYTECODE; disable cache before loading the pinned owner.
        sys.dont_write_bytecode = True
        spec=importlib.util.spec_from_file_location('_bound_original_hk_owner',p)
        owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner)
        if hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
            phase='OWNER_IDENTITY';raise ValueError('owner bytes changed')
        phase='OWNER_CALL'
        result=owner.ensure_hk_connect_universe(pathlib.Path(sys.argv[3]),sys.argv[4])
        phase='OWNER_RESULT'
        if not isinstance(result,dict) or result.get('ok') is not True:
            result={'ok':False,'reason':'HK_UNIVERSE_ORIGINAL_OWNER_FAILED','owner_failure':diagnostic()}
        else:
            result={'ok':True,'trade_date':result.get('trade_date'),'owner_sha256':expected,
                    'artifact_sha256':result.get('artifact_sha256'),'code_count':result.get('code_count')}
    print(marker+json.dumps(result,sort_keys=True))
    raise SystemExit(0 if result.get('ok') is True else 2)
except Exception as exc:
    print(marker+json.dumps({'ok':False,'reason':'HK_UNIVERSE_ORIGINAL_OWNER_FAILED',
                            'owner_failure':diagnostic(exc)},sort_keys=True))
    raise SystemExit(2)
"""


def _validate_owner_failure(value: dict, owner_sha256: str) -> dict:
    """Whitelist structure, not exception text. No URLs, absolute paths or stderr."""
    import re
    allowed = {'RuntimeError','ValueError','TypeError','KeyError','ImportError','ModuleNotFoundError',
               'OSError','FileNotFoundError','PermissionError','TimeoutError','ConnectionError','AssertionError',
               'TimeoutExpired','OTHER'}
    if (not isinstance(value, dict) or set(value) != {'schema_version','owner_sha256','phase','causes','frames'}
            or value.get('schema_version') != 'v4.manager_owner_failure.v1'
            or not re.fullmatch(r'[0-9a-f]{64}', str(owner_sha256))
            or value.get('owner_sha256') != owner_sha256
            or value.get('phase') not in {'OWNER_IMPORT','OWNER_IDENTITY','OWNER_CALL','OWNER_RESULT',
                                          'OWNER_START','OWNER_TIMEOUT','OWNER_READBACK'}):
        raise ValueError('OWNER_DIAGNOSTIC_INVALID')
    causes=value['causes'];frames=value['frames']
    if not isinstance(causes,list) or len(causes)>3 or not isinstance(frames,list) or len(frames)>8:
        raise ValueError('OWNER_DIAGNOSTIC_BOUNDS')
    for cause in causes:
        if not isinstance(cause,dict) or set(cause)!={'type'} or cause['type'] not in allowed:
            raise ValueError('OWNER_DIAGNOSTIC_CAUSE')
    for frame in frames:
        if (not isinstance(frame,dict) or set(frame)!={'file','function','line'}
                or frame['file']!='stage_center/hk_universe_preflight.py'
                or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}|<(module|listcomp|dictcomp|setcomp|genexpr|lambda)>',str(frame['function']))
                or type(frame['line']) is not int or not 0<frame['line']<=100000):
            raise ValueError('OWNER_DIAGNOSTIC_FRAME')
    return json.loads(json.dumps(value))


def _owner_transport_failure(owner_sha256: str, phase: str, exc: Exception) -> dict:
    kind=type(exc).__name__
    if kind not in {'TimeoutExpired','OSError','FileNotFoundError','PermissionError'}:kind='OTHER'
    return _validate_owner_failure(dict(schema_version='v4.manager_owner_failure.v1',
        owner_sha256=owner_sha256,phase=phase,causes=[{'type':kind}],frames=[]),owner_sha256)


def _save_owner_failure(state: Path, date: str, error: EvidenceError, at: datetime) -> dict:
    detail=dict(error.diagnostic)
    value=getattr(error,'owner_failure',None)
    if value is None:return detail
    value=_validate_owner_failure(value,detail['source_code_sha256'])
    body=dict(schema_version='v4.manager_owner_failure_record.v1',trade_date=date,slot='1530',
              observed_at=at.isoformat(),diagnostic=value,**FOUR_FLAGS)
    raw=encoded(body);ref=f'workbench_research/{date}/diagnostics/{digest(raw)}.owner.json'
    path=resolve(state,ref)
    if not atomic_create(path,raw) and path.read_bytes()!=raw:
        raise EvidenceError('OWNER_DIAGNOSTIC_IMMUTABLE_CONFLICT',layer='UNIVERSE_OWNER',kind='CONFLICT')
    detail['artifact_ref']=ref
    return detail


def _history_preflight(root: Path | None, date: str, codes: list[str], clock: Callable[[],datetime]) -> dict:
    """Read existing authorities only. Not a 1530 history witness or success."""
    import re
    started=clock()
    try:
        from v4.manager_research.workspace_plan import read_rebound_history
        bound=require_authority_root(root)
        value=read_rebound_history(bound,date,codes,now=started)
        status=value.get('status')
        if status not in {'READY','PARTIAL','CANNOT_CONFIRM'}:raise ValueError('REBOUND_PREFLIGHT_STATUS')
        gaps=[g for g in value.get('gaps',[]) if isinstance(g,str) and re.fullmatch(r'[A-Z0-9_:.-]{1,160}',g)]
        if len(gaps)!=len(value.get('gaps',[])):raise ValueError('REBOUND_PREFLIGHT_GAPS')
        return dict(status=status,started_at=started.isoformat(),completed_at=clock().isoformat(),
                    source_files=value.get('source_files',[]),gaps=gaps,
                    covered_symbols=len(value.get('symbols',{})),eligible_symbols=len(codes),
                    volume_unit=value.get('volume_unit'),snapshot_requested=False,
                    history_witness_written=False,admission_effect='NONE_REVALIDATE_AT_CAPTURE')
    except (ValueError,OSError,ImportError,TypeError,KeyError):
        return dict(status='CANNOT_CONFIRM',started_at=started.isoformat(),completed_at=clock().isoformat(),
                    source_files=[],gaps=['REBOUND_DEPENDENCY_PREFLIGHT_UNAVAILABLE'],
                    covered_symbols=None,eligible_symbols=len(codes),volume_unit=None,
                    snapshot_requested=False,history_witness_written=False,
                    admission_effect='NONE_REVALIDATE_AT_CAPTURE')


def _invoke_universe_owner(*, universe_root: Path, trade_date: str, futu_python: Path,
                           owner_root: Path, owner_sha256: str, clock: Callable[[], datetime]) -> dict:
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        owner = load_universe_owner(owner_root, owner_sha256)
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
    now = clock().astimezone(HK)
    remaining = (now.replace(hour=15, minute=32, second=0, microsecond=0) - now).total_seconds()
    if now.strftime('%Y%m%d') != trade_date or remaining <= 0:
        raise EvidenceError('EXACT_1530_SNAPSHOT_WINDOW_MISSED', layer='CAPTURE_WINDOW',
                            kind='EXPIRED', field='snapshot')
    python = _futu_executable_path(futu_python, owner_sha256=owner_sha256)
    try:
        completed = subprocess.run(
            [str(python), '-I', '-c', _OWNER_CALL, str(Path(owner.__file__)), owner_sha256,
             str(universe_root), trade_date],
            capture_output=True, text=True, timeout=max(0.1, min(45.0, remaining)),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        error=EvidenceError('HK_UNIVERSE_OWNER_TIMEOUT_OR_START_FAILED', layer='UNIVERSE_OWNER',
                            kind='EXECUTION_FAILED', field='ensure_hk_connect_universe', owner_sha256=owner_sha256)
        error.owner_failure=_owner_transport_failure(owner_sha256,
            'OWNER_TIMEOUT' if isinstance(exc,subprocess.TimeoutExpired) else 'OWNER_START',exc)
        raise error from exc
    try:
        lines = [line[len(_OWNER_MARKER):] for line in completed.stdout.splitlines()
                 if line.startswith(_OWNER_MARKER)]
        if len(lines) != 1:
            raise ValueError('original owner result marker count')
        result = json.loads(lines[0])
    except (ValueError, TypeError) as exc:
        raise EvidenceError('HK_UNIVERSE_OWNER_RESULT_INVALID', layer='UNIVERSE_OWNER',
                            field='owner_result', owner_sha256=owner_sha256) from exc
    if (completed.returncode != 0 or not isinstance(result, dict) or result.get('ok') is not True
        or result.get('trade_date') != trade_date or result.get('owner_sha256') != owner_sha256):
        error=EvidenceError('HK_UNIVERSE_ORIGINAL_OWNER_FAILED', layer='UNIVERSE_OWNER',
                            kind='EXECUTION_FAILED', field='ensure_hk_connect_universe', owner_sha256=owner_sha256)
        if isinstance(result,dict) and 'owner_failure' in result:
            try:error.owner_failure=_validate_owner_failure(result['owner_failure'],owner_sha256)
            except ValueError as exc:
                raise EvidenceError('HK_UNIVERSE_OWNER_DIAGNOSTIC_INVALID',layer='UNIVERSE_OWNER',
                    kind='INVALID',field='owner_result',owner_sha256=owner_sha256) from exc
            if error.owner_failure['phase']=='OWNER_IDENTITY':
                error=EvidenceError('HK_UNIVERSE_OWNER_SHA_MISMATCH',layer='UNIVERSE_OWNER',
                    kind='CONFLICT',field='source_code_sha256',owner_sha256=owner_sha256)
        raise error
    return result  # caller MUST read/validate the original artifact+manifest+receipt+current


def _universe_input(*, universe_root: Path, trade_date: str, futu_python: Path,
                    universe_owner_root: Path | None, universe_owner_sha256: str | None,
                    clock: Callable[[], datetime], allow_prepare: bool):
    options = {'authority_owner_root': universe_owner_root,
               'authority_owner_sha256': universe_owner_sha256, 'clock': clock}
    try:
        return read_universe_evidence(universe_root, trade_date, **options)
    except EvidenceError as exc:
        # A bad existing chain is never overwritten or 'fixed' by copying data.
        if (not allow_prepare or str(exc) not in
            {'HK_CONNECT_EXACT_UNIVERSE_MISSING', 'HK_UNIVERSE_AUTHORITY_CHAIN_MISSING'}):
            raise
        if universe_owner_root is None or universe_owner_sha256 is None:
            raise  # preserve the precise input failure if no producer binding was supplied
    _invoke_universe_owner(universe_root=universe_root, trade_date=trade_date,
        futu_python=futu_python, owner_root=universe_owner_root,
        owner_sha256=universe_owner_sha256, clock=clock)
    return read_universe_evidence(universe_root, trade_date, **options)


def prepare_universe(*, universe_root: Path, futu_python: Path, trade_date: str,
                     manager_state_root: Path, universe_owner_root: Path,
                     universe_owner_sha256: str, app_root: Path = APP_ROOT,
                     clock: Callable[[], datetime] = _clock,
                     rebound_authority_root: Path | None = None) -> dict:
    """Dependency of existing 1500 hourly work; no snapshot, candidate or 1530 attempt write."""
    now = clock()
    if now.tzinfo is None:
        raise EvidenceError('CLOCK_MUST_BE_AWARE', layer='CONFIGURATION', field='clock')
    now = now.astimezone(HK)
    state = _root(manager_state_root, 'V4_MANAGER_STATE_ROOT_REQUIRED')
    root = _root(universe_root, 'V35_UNIVERSE_ROOT_REQUIRED')
    if _root(app_root, 'V4_APP_ROOT_REQUIRED') != APP_ROOT:
        raise EvidenceError('V4_IMPORT_ORIGIN_MISMATCH', layer='CONFIGURATION', field='app_root')
    try:
        if now.strftime('%Y%m%d') != trade_date:
            raise EvidenceError('LIVE_CLOSE_DISCOVERY_CURRENT_DATE_ONLY', layer='CONFIGURATION', field='trade_date')
        market = resolve_market_states(load_market_calendar(), trade_date)['hk_connect']
        if market in {TradingDayState.NON_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM}:
            return _result(trade_date, 'NOT_APPLICABLE', 'NO_HK_CONNECT_1530_SESSION', state_root=str(state))
        if market is not TradingDayState.FULL_TRADING_DAY:
            raise EvidenceError('TRADING_CALENDAR_UNVERIFIED', layer='CONFIGURATION', field='calendar')
        if now.time() >= time(15, 32):
            raise EvidenceError('EXACT_1530_SNAPSHOT_WINDOW_MISSED', layer='CAPTURE_WINDOW',
                                kind='EXPIRED', field='snapshot')
        universe = _universe_input(universe_root=root, trade_date=trade_date, futu_python=futu_python,
            universe_owner_root=universe_owner_root, universe_owner_sha256=universe_owner_sha256,
            clock=clock, allow_prepare=True)
        return _result(trade_date, 'UNIVERSE_READY', state_root=str(state),
            authority_sha256=universe.source['sha256'], authority_run_id=universe.source['run_id'],
            authority_available_at=universe.source['available_at'], code_count=len(universe.codes),
            universe_owner_sha256=universe_owner_sha256,
            history_preflight=_history_preflight(rebound_authority_root,trade_date,list(universe.codes),clock))
    except EvidenceError as exc:
        return _result(trade_date, 'INPUT_MISSING' if exc.diagnostic['kind']=='MISSING' else 'FAILED',
            str(exc), state_root=str(state), failure_diagnostic=_save_owner_failure(state,trade_date,exc,clock()))


def materialize(*,data_root: Path,universe_root: Path,futu_python: Path,trade_date: str,
                manager_state_root: Path | None,news_owner_root: Path | None,
                app_root: Path=APP_ROOT,clock: Callable[[],datetime]=_clock,
                universe_owner_root: Path | None = None, universe_owner_sha256: str | None = None,
                snapshot_fetcher: Callable[...,Any]=fetch_futu_snapshot,
                rebound_authority_root: Path | None = None) -> dict:
    """Clock/fetcher seams are for isolated SIMULATED tests; CLI has no overrides."""
    now=clock()
    if now.tzinfo is None: raise EvidenceError('CLOCK_MUST_BE_AWARE')
    now=now.astimezone(HK)
    if _root(app_root,'V4_APP_ROOT_REQUIRED')!=APP_ROOT: raise EvidenceError('V4_IMPORT_ORIGIN_MISMATCH')
    state=_root(manager_state_root,'V4_MANAGER_STATE_ROOT_REQUIRED')
    data=_root(data_root,'V35_DATA_ROOT_REQUIRED'); universe_root=_root(universe_root,'V35_UNIVERSE_ROOT_REQUIRED')
    news_owner=_root(news_owner_root,'ACTUAL_NEWS_OWNER_ROOT_REQUIRED')
    if not (news_owner/'ops/collect_hourly_research_input.py').is_file():
        raise EvidenceError('ACTUAL_NEWS_OWNER_IMPORT_CLOSURE_MISSING')
    if trade_date!=now.strftime('%Y%m%d'):
        raise EvidenceError('LIVE_CLOSE_DISCOVERY_CURRENT_DATE_ONLY')
    def fail(status: str,reason: str, error: EvidenceError | None = None) -> dict:
        detail = _save_owner_failure(state,trade_date,error or EvidenceError(reason),clock())
        terminal = detail['kind'] == 'EXPIRED'
        _status(state,trade_date,status,reason,clock(),diagnostic=detail)
        return _result(trade_date,status,reason,state_root=str(state),
            failure_diagnostic=detail, terminal=terminal,
            failure_class='NOT_DUE' if terminal else
                ('UPSTREAM_NOT_READY' if detail['kind'] in {'MISSING','EXECUTION_FAILED'} else 'INVALID_INPUT'))
    states=resolve_market_states(load_market_calendar(),trade_date)
    if states['hk_connect'] in {TradingDayState.NON_TRADING_DAY,TradingDayState.HALF_TRADING_DAY_AM}:
        return fail('NOT_APPLICABLE','NO_HK_CONNECT_1530_SESSION')
    if states['hk_connect'] is not TradingDayState.FULL_TRADING_DAY:
        return fail('INPUT_MISSING','TRADING_CALENDAR_UNVERIFIED')
    if now.time()<time(15,30): return fail('PENDING_SLOT','WAITING_FOR_1530')
    lock=resolve(state,f'workbench_research/{trade_date}/1530.lock')
    try:
        with owned_interprocess_lock(lock,timeout_seconds=0,timeout_message='MANAGER_SLOT_LOCKED',timeout_error=EvidenceError):
            existing=_published_result(state,trade_date,'ALREADY_EXISTS',rebound_authority_root=rebound_authority_root)
            if existing is not None: return existing
            snapshot_path=resolve(state,f'workbench_research/{trade_date}/inputs/1530_futu_snapshot.json')
            # Terminal capture-window decision precedes a missing authority. After
            # 15:32 no producer/quote call can retroactively create this snapshot.
            if not snapshot_path.is_file() and clock().astimezone(HK).time() >= time(15,32):
                error = EvidenceError('EXACT_1530_SNAPSHOT_WINDOW_MISSED', layer='CAPTURE_WINDOW',
                    kind='EXPIRED', field='snapshot',
                    artifact_ref=f'workbench_research/{trade_date}/inputs/1530_futu_snapshot.json')
                return fail('INPUT_MISSING',str(error),error)
            _status(state,trade_date,'PENDING_SLOT','EXECUTION_STARTED',now)
            try:
                universe = _universe_input(universe_root=universe_root, trade_date=trade_date,
                    futu_python=futu_python, universe_owner_root=universe_owner_root,
                    universe_owner_sha256=universe_owner_sha256, clock=clock,
                    allow_prepare=not snapshot_path.exists())
            except EvidenceError as error:
                if (snapshot_path.is_file()
                        and clock().astimezone(HK).time() >= time(15,32)
                        and error.diagnostic.get('kind') == 'MISSING'
                        and str(error) in {'HK_CONNECT_EXACT_UNIVERSE_MISSING',
                                           'HK_UNIVERSE_AUTHORITY_CHAIN_MISSING'}):
                    expired = EvidenceError('EXACT_1530_SNAPSHOT_WINDOW_MISSED', layer='CAPTURE_WINDOW',
                        kind='EXPIRED', field='snapshot',
                        artifact_ref=f'workbench_research/{trade_date}/inputs/1530_futu_snapshot.json')
                    return fail('INPUT_MISSING',str(expired),expired)
                return fail('INPUT_MISSING' if error.diagnostic['kind']=='MISSING' else 'FAILED',str(error),error)
            try:
                rebound_authority_root = require_authority_root(rebound_authority_root)
            except (ValueError,OSError) as exc:
                code = str(exc) if str(exc).startswith('REBOUND_HISTORY_AUTHORITY_') else 'REBOUND_HISTORY_AUTHORITY_ROOT_INVALID'
                error=EvidenceError(code,layer='CONFIGURATION',kind='INVALID',field='rebound_authority_root')
                return fail('FAILED',code,error)
            if not snapshot_path.exists():
                capture_history(state,trade_date,list(universe.codes),root=rebound_authority_root,clock=clock)
                started=clock().astimezone(HK)
                if started.strftime('%Y%m%d')!=trade_date or started.time()>=time(15,32):
                    error=EvidenceError('EXACT_1530_SNAPSHOT_WINDOW_MISSED',layer='CAPTURE_WINDOW',kind='EXPIRED',field='snapshot')
                    return fail('INPUT_MISSING',str(error),error)
                remaining=(started.replace(hour=15,minute=32,second=0,microsecond=0)-started).total_seconds()
                try: rows,errors=snapshot_fetcher(futu_python,universe.codes,timeout_seconds=min(30.0,remaining))
                except Exception:
                    error=EvidenceError('EXISTING_FUTU_BRIDGE_FAILED',kind='EXECUTION_FAILED',field='snapshot_fetch')
                    return fail('FAILED',str(error),error)
                available=clock().astimezone(HK)  # actual return time, not a quote's timestamp
                if available.strftime('%Y%m%d')!=trade_date or available.time()>=time(15,32):
                    error=EvidenceError('SNAPSHOT_RETURNED_AFTER_1530_WINDOW',layer='CAPTURE_WINDOW',kind='EXPIRED',field='available_at')
                    return fail('INPUT_MISSING',str(error),error)
                persist_snapshot(state,trade_date=trade_date,rows=rows,errors=errors,started_at=started,
                                 available_at=available,universe=universe,app_root=APP_ROOT)
            snap=read_snapshot_evidence(state,trade_date,as_of=clock(),universe=universe,app_root=APP_ROOT)
            universe=universe_at_snapshot(universe,snap)
            as_of=aware(snap.source['available_at'])
            # Read only the pre-capture witness. Recovery never substitutes a
            # newly published/updated daily panel for history available at 1530.
            try:
                history=read_history(state,trade_date,as_of=as_of,root=rebound_authority_root)
            except (ValueError,OSError,ImportError,KeyError,TypeError) as exc:
                import re
                code=str(exc) if re.fullmatch(r'REBOUND_[A-Z0-9_]{1,120}',str(exc)) else 'REBOUND_HISTORY_VALIDATION_FAILED'
                error=EvidenceError(code,layer='CONFIGURATION',field='rebound_history',
                    artifact_ref=f'workbench_research/{trade_date}/inputs/1530_rebound_history.json')
                return fail('FAILED',code,error)
            # Ambiguous/duplicate quote names never establish direct mappings.
            from collections import Counter
            counts=Counter(r.get('code') for r in snap.rows)
            names={r['code']:str(r.get('name') or r['code']) for r in snap.rows
                   if r.get('code') in universe.codes and counts[r['code']]==1}
            paths,prior_date=_news_paths(data,trade_date)
            events,gaps=read_catalyst_events(paths,as_of=as_of,universe_names=names,reference_root=data,owner_root=news_owner)
            if not paths: gaps.append('CATALYST_INPUT_MISSING')
            prior=read_prior_evidence(state,expected_date=prior_date,as_of=as_of) if prior_date else None
            if prior is None: gaps.append('PRIOR_WORKBENCH_NOT_VERIFIED')
            payload=build_workbench_payload(trade_date=trade_date,as_of=as_of,generated_at=clock(),
                universe_source=universe.source,eligible_symbols=universe.codes,snapshot_source=snap.source,
                snapshot_rows=snap.rows,snapshot_errors=snap.errors,universe_evidence=universe,snapshot_evidence=snap,
                catalyst_events=events,catalyst_gaps=gaps,prior_evidence=prior,
                history_evidence=history,state_root=state)
            validated=validate_workbench_payload(payload,expected_date=trade_date)
            path=resolve(state,f'workbench_research/{trade_date}/1530.json')
            raw=encoded(validated)
            if not atomic_create(path,raw) and path.read_bytes()!=raw:
                raise EvidenceError('WORKBENCH_IMMUTABLE_CONFLICT')
            result=_published_result(state,trade_date,'MATERIALIZED',rebound_authority_root=rebound_authority_root)
            if result is None: raise EvidenceError('WORKBENCH_PUBLICATION_MISSING')
            return result
    except EvidenceError as error:
        if str(error)=='MANAGER_SLOT_LOCKED':
            return _result(trade_date,'FAILED','MANAGER_SLOT_LOCKED',state_root=str(state))
        return fail('FAILED',str(error),error)
    except (ValueError,OSError,TypeError,KeyError):
        return fail('FAILED','MANAGER_MATERIALIZATION_VALIDATION_FAILED')


def _catalyst_main(argv: Sequence[str]) -> int:
    """One-shot entry to the SAME manager material owner; no new collector."""
    parser = argparse.ArgumentParser(description="Project independent catalyst observations from existing owner materials")
    parser.add_argument("--catalysts-only", action="store_true")
    for name in ("state-root", "app-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("data-root", "news-owner-root", "admission-bundle"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--admission-sha256")
    parser.add_argument("--trade-date", required=True)
    args = parser.parse_args(argv)
    from v4.manager_research.service import ManagerResearchJobService
    from v4.manager_research.store import ManagerResearchStore
    from v4.manager_research.materials import MaterialStore
    state = _root(args.state_root, "V4_MANAGER_STATE_ROOT_REQUIRED")
    if _root(args.app_root, "V4_APP_ROOT_REQUIRED") != APP_ROOT:
        raise ValueError("V4_IMPORT_ORIGIN_MISMATCH")
    service = ManagerResearchJobService(ManagerResearchStore(state), None, None,
        material_store=MaterialStore(state / "materials"), catalyst_data_root=args.data_root,
        catalyst_news_owner_root=args.news_owner_root)
    try:
        if args.admission_bundle:
            if not args.admission_sha256:
                raise ValueError("CATALYST_ADMISSION_EXPECTED_SHA_REQUIRED")
            if json.loads(args.admission_bundle.read_bytes()).get("target_trade_date") != args.trade_date:
                raise ValueError("CATALYST_ADMISSION_TARGET_MISMATCH")
            service.admit_catalyst_materials(args.admission_bundle, expected_sha256=args.admission_sha256)
        result = service.refresh_catalyst_observations(args.trade_date)
        # Actual readback repeats source closure; publishing alone is not success.
        if service.get_catalyst_observations(args.trade_date) != result:
            raise ValueError("CATALYST_READBACK_MISMATCH")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        service.close()


def main(argv: Sequence[str] | None=None) -> int:
    supplied = list(argv) if argv is not None else sys.argv[1:]
    if "--catalysts-only" in supplied:
        return _catalyst_main(supplied)
    if '--close-recapture' in supplied:
        parser=argparse.ArgumentParser(description='Explicit late PyTDX HK minute observation; never historical 1530')
        parser.add_argument('--close-recapture',action='store_true')
        parser.add_argument('--state-root',type=Path,required=True)
        parser.add_argument('--universe-root',type=Path,required=True)
        parser.add_argument('--trade-date',required=True)
        parser.add_argument('--app-root',type=Path,default=APP_ROOT)
        parser.add_argument('--pytdx-python',type=Path,default=Path(os.environ.get('V35_HK_0_2_REAL_PYTHON','')))
        parser.add_argument('--provider-root',type=Path,default=Path(os.environ['V35_SHARED_PACKAGE_ROOT'])
            if os.environ.get('V35_SHARED_PACKAGE_ROOT') else APP_ROOT/'upstreams/v3_shared_data')
        args=parser.parse_args(supplied)
        result=recapture_close_minutes(manager_state_root=args.state_root,universe_root=args.universe_root,
            pytdx_python=args.pytdx_python,trade_date=args.trade_date,app_root=args.app_root,
            provider_root=args.provider_root)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        return 0 if result['status'] in {'MATERIALIZED','PARTIAL','ALREADY_EXISTS','NOT_APPLICABLE'} else 2
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('data-root','universe-root','futu-python','state-root','app-root','news-owner-root'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--trade-date',required=True)
    parser.add_argument('--universe-only',action='store_true')
    parser.add_argument('--universe-owner-root',type=Path)
    parser.add_argument('--universe-owner-sha256')
    parser.add_argument('--rebound-authority-root',type=Path)
    args=parser.parse_args(argv)
    try:
        if args.universe_only:
            result=prepare_universe(universe_root=args.universe_root,futu_python=args.futu_python,
                trade_date=args.trade_date,manager_state_root=args.state_root,
                universe_owner_root=args.universe_owner_root,universe_owner_sha256=args.universe_owner_sha256,
                app_root=args.app_root,rebound_authority_root=args.rebound_authority_root)
        else:
            result=materialize(data_root=args.data_root,universe_root=args.universe_root,futu_python=args.futu_python,
                trade_date=args.trade_date,manager_state_root=args.state_root,news_owner_root=args.news_owner_root,
                app_root=args.app_root,universe_owner_root=args.universe_owner_root,
                universe_owner_sha256=args.universe_owner_sha256,rebound_authority_root=args.rebound_authority_root)
    except Exception as error:
        # An import error before main naturally has a non-zero process exit;
        # configuration errors here never masquerade as a successful run.
        result=_result(args.trade_date,'FAILED','MATERIALIZER_CONFIGURATION_OR_DATE_INVALID',exception_type=type(error).__name__)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if result['status'] in {'MATERIALIZED','ALREADY_EXISTS','NOT_APPLICABLE','UNIVERSE_READY'} else 2

if __name__=='__main__': raise SystemExit(main())
