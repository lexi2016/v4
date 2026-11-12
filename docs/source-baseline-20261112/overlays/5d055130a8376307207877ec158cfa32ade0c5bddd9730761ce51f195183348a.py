"""One-shot research materializer invoked by the existing hourly owner.

1500 may prepare its original membership dependency; only 1530 captures quotes.

No scheduler, subscription, second quote feed or GET side effect is defined.
Data/universe remain in V35; output MUST bind to the V4 API's manager state.
"""
from __future__ import annotations
import argparse
from datetime import datetime, time
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

APP_ROOT=Path(__file__).resolve().parents[1]
for _path in (APP_ROOT/'upstreams',APP_ROOT/'upstreams'/'v3_shared_data'):
    if str(_path) not in sys.path: sys.path.insert(0,str(_path))

from apps.api.v4_api.manager_workbench_router import validate_workbench_payload, _empty_envelope
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


def _clock() -> datetime: return datetime.now(HK)


def _root(value: Path | None, code: str) -> Path:
    if value is None or not Path(value).expanduser().is_absolute(): raise EvidenceError(code)
    return Path(value).expanduser().resolve()


def _status(root: Path, date: str, status: str, reason: str, at: datetime, *, diagnostic: dict | None = None) -> None:
    from infrastructure.manager_close_attempt import write_attempt
    write_attempt(root,date,status,reason,at,diagnostic=diagnostic)


def _result(date: str,status: str,reason: str | None=None,**values: Any) -> dict:
    return {'schema_version':RESULT_SCHEMA,'status':status,'trade_date':date,'slot':'1530',
            'reason':reason,'module_origin':str(Path(__file__).resolve()),
            'module_sha256':digest(Path(__file__).read_bytes()),**values,**FOUR_FLAGS}


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
import contextlib, hashlib, importlib.util, json, pathlib, sys
marker = "V4_ORIGINAL_HK_UNIVERSE_RESULT="
p = pathlib.Path(sys.argv[1]); expected = sys.argv[2]
if hashlib.sha256(p.read_bytes()).hexdigest() != expected:
    raise SystemExit(3)
spec = importlib.util.spec_from_file_location('_bound_original_hk_owner', p)
owner = importlib.util.module_from_spec(spec); spec.loader.exec_module(owner)
if hashlib.sha256(p.read_bytes()).hexdigest() != expected:
    raise SystemExit(3)
try:
    with contextlib.redirect_stdout(sys.stderr):
        result = owner.ensure_hk_connect_universe(pathlib.Path(sys.argv[3]), sys.argv[4])
    print(marker + json.dumps({'ok': result.get('ok'), 'status': result.get('status'),
                      'trade_date': result.get('trade_date'), 'owner_sha256': expected,
                      'artifact_sha256': result.get('artifact_sha256'),
                      'code_count': result.get('code_count')}, sort_keys=True))
except Exception:
    # Do not echo provider exceptions (may include network URLs, credentials).
    print(marker + json.dumps({'ok': False, 'reason': 'HK_UNIVERSE_ORIGINAL_OWNER_FAILED'}))
    raise SystemExit(2)
"""


def _invoke_universe_owner(*, universe_root: Path, trade_date: str, futu_python: Path,
                           owner_root: Path, owner_sha256: str, clock: Callable[[], datetime]) -> dict:
    owner = load_universe_owner(owner_root, owner_sha256)
    now = clock().astimezone(HK)
    remaining = (now.replace(hour=15, minute=32, second=0, microsecond=0) - now).total_seconds()
    if now.strftime('%Y%m%d') != trade_date or remaining <= 0:
        raise EvidenceError('EXACT_1530_SNAPSHOT_WINDOW_MISSED', layer='CAPTURE_WINDOW',
                            kind='EXPIRED', field='snapshot')
    python = _root(futu_python, 'EXISTING_FUTU_PYTHON_REQUIRED')
    if not python.is_file():
        raise EvidenceError('EXISTING_FUTU_PYTHON_MISSING', layer='UNIVERSE_OWNER',
                            kind='MISSING', field='futu_python', owner_sha256=owner_sha256)
    try:
        completed = subprocess.run(
            [str(python), '-I', '-c', _OWNER_CALL, str(Path(owner.__file__)), owner_sha256,
             str(universe_root), trade_date],
            capture_output=True, text=True, timeout=max(0.1, min(45.0, remaining)),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvidenceError('HK_UNIVERSE_OWNER_TIMEOUT_OR_START_FAILED', layer='UNIVERSE_OWNER',
                            kind='EXECUTION_FAILED', field='ensure_hk_connect_universe',
                            owner_sha256=owner_sha256) from exc
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
        raise EvidenceError('HK_UNIVERSE_ORIGINAL_OWNER_FAILED', layer='UNIVERSE_OWNER',
                            kind='EXECUTION_FAILED', field='ensure_hk_connect_universe',
                            owner_sha256=owner_sha256)
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
                     clock: Callable[[], datetime] = _clock) -> dict:
    """Dependency of existing 1500 hourly work; no snapshot, candidate or 1530 attempt write."""
    now = clock()
    if now.tzinfo is None:
        raise EvidenceError('CLOCK_MUST_BE_AWARE', layer='CONFIGURATION', field='clock')
    now = now.astimezone(HK)
    state = _root(manager_state_root, 'V4_MANAGER_STATE_ROOT_REQUIRED')
    root = _root(universe_root, 'V4_UNIVERSE_ROOT_REQUIRED')
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
            universe_owner_sha256=universe_owner_sha256)
    except EvidenceError as exc:
        return _result(trade_date, 'INPUT_MISSING' if exc.diagnostic['kind']=='MISSING' else 'FAILED',
            str(exc), state_root=str(state), failure_diagnostic=exc.diagnostic)


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
    data=_root(data_root,'V4_DATA_ROOT_REQUIRED'); universe_root=_root(universe_root,'V4_UNIVERSE_ROOT_REQUIRED')
    news_owner=_root(news_owner_root,'ACTUAL_NEWS_OWNER_ROOT_REQUIRED')
    if not (news_owner/'ops/collect_hourly_research_input.py').is_file():
        raise EvidenceError('ACTUAL_NEWS_OWNER_IMPORT_CLOSURE_MISSING')
    if trade_date!=now.strftime('%Y%m%d'):
        raise EvidenceError('LIVE_CLOSE_DISCOVERY_CURRENT_DATE_ONLY')
    def fail(status: str,reason: str, error: EvidenceError | None = None) -> dict:
        detail = (error or EvidenceError(reason)).diagnostic
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
                if started.time()>=time(15,32):
                    error=EvidenceError('EXACT_1530_SNAPSHOT_WINDOW_MISSED',layer='CAPTURE_WINDOW',kind='EXPIRED',field='snapshot')
                    return fail('INPUT_MISSING',str(error),error)
                try: rows,errors=snapshot_fetcher(futu_python,universe.codes)
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
                app_root=args.app_root)
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
