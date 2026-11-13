"""Candidate Stage7 A-share capture through the existing PyTDX HQ collector."""
from dataclasses import replace
from datetime import datetime, time
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

from infrastructure.owned_io import SafeRoot
from stage_center.acquisition import build_plan
from stage_center.calendar import TradingDayState, calendar_provenance, resolve_market_states
from stage_center.contracts import EIGHT_STAGES, SAFETY_FLAGS
from stage_center.live_collectors import _shared_scripts_root, _tdx_code, collect_a_share_hq_minute
from stage_center.raw_store import RawStore
from stage_center.runner import _project_raw_rows


STAGE_ID = 'STAGE_1445_1500'
MARKET = 'A_SHARE'
STAGE = next(stage for stage in EIGHT_STAGES if stage.stage_id == STAGE_ID)
SHANGHAI = ZoneInfo('Asia/Shanghai')
RESEARCH_FLAGS = {**SAFETY_FLAGS, 'RESEARCH_ONLY': True}
HQ_MARKER = '__PYTDX_HQ_MINUTE_JSON__'
TIME_BASIS = 'PYTDX_OWNER_PROVIDER_OR_FIXED_SESSION_ORDINAL'
TIME_LIMITATION = 'PYTDX_WIRE_TIMESTAMP_NATIVE_UNVERIFIED'
VERIFIED_HQ_MODULE_SHA256 = '7b5f062e6c1231fa5edc7db0de5406066220e69cfe3605bf5b13fd3e0b8ad18f'
SYSTEM_SCRATCH_ROOT = Path('/tmp').resolve()


def _private_output(path, candidate_root, *, fixture):
    output = Path(path)
    if not output.is_absolute() or not output.is_dir() or output.resolve() != output:
        raise ValueError('STAGE7_CAPTURE_EXPLICIT_ISOLATED_OUTPUT_ROOT_REQUIRED')
    if output.is_relative_to(candidate_root) or candidate_root.is_relative_to(output):
        raise ValueError('STAGE7_CAPTURE_OUTPUT_OVERLAPS_CANDIDATE_INPUT')
    if not fixture:
        meta = output.stat()
        # A caller-created private temporary directory, never a live owner
        # root or arbitrary descendant. One fresh root per manual attempt.
        if (output.parent != SYSTEM_SCRATCH_ROOT or not output.name.startswith('v4-stage7-candidate.')
                or meta.st_uid != os.geteuid() or stat.S_IMODE(meta.st_mode) & 0o077
                or any(output.iterdir())):
            raise ValueError('STAGE7_CAPTURE_FRESH_PRIVATE_SCRATCH_REQUIRED')
    if any((output / name).exists() or (output / name).is_symlink()
           for name in ('latest.json', 'current.json', 'runs', 'raw', 'selection')):
        raise ValueError('STAGE7_CAPTURE_OUTPUT_IS_OWNER_STORE')
    return output


def _now():
    return datetime.now(SHANGHAI)


def _wall(clock):
    value = clock()
    if value.utcoffset() is None:
        raise ValueError('STAGE7_CAPTURE_CLOCK_OFFSET_REQUIRED')
    return value.astimezone(SHANGHAI)


def _capture_times(trade_date):
    day = datetime.strptime(trade_date, '%Y%m%d').date()
    if day.strftime('%Y%m%d') != trade_date or resolve_market_states(trade_date)['a_share'] != TradingDayState.FULL_TRADING_DAY:
        raise ValueError('STAGE7_CAPTURE_A_TRADE_DATE_INVALID')
    return tuple(datetime.combine(day, time.fromisoformat(hour), SHANGHAI)
                 for hour in (STAGE.window.split('-')[0], STAGE.cutoff))


def prepare_plan(candidate_root, trade_date, expected_current_sha256):
    _capture_times(trade_date)
    if not expected_current_sha256:
        raise ValueError('STAGE7_CAPTURE_CANDIDATE_SHA_REQUIRED')
    plan = build_plan(candidate_root, trade_date, STAGE_ID, expected_current_sha256=expected_current_sha256)
    for code in plan.codes_for(MARKET):
        if code.partition('.')[0] not in {'A', 'SH', 'SZ', 'BJ'}:
            raise ValueError('STAGE7_CAPTURE_CANDIDATE_MARKET_INVALID')
    return replace(plan, markets=(MARKET,), a_share_route='pytdx_hq_large_universe', hk_route='NOT_APPLICABLE')


def dry_run(candidate_root, trade_date, expected_current_sha256):
    plan = prepare_plan(candidate_root, trade_date, expected_current_sha256)
    start, cutoff = _capture_times(trade_date)
    return {
        **_identity(plan), 'status': 'DRY_RUN_READY', 'capture_not_before': start.isoformat(),
        'cutoff_at': cutoff.isoformat(), 'provider_called': False, 'natural_verified': False,
        'formal_pool_ready': False,
    }


def _identity(plan):
    return dict(
        schema='v4.stage_center.a_stage7_precapture.v1', trade_date=plan.trade_date, stage_id=STAGE_ID,
        market=MARKET, collector='pytdx_hq', candidate_current_sha256=plan.candidate_input.current_sha256,
        candidate_artifact_sha256=plan.candidate_input.artifact_sha256,
        candidate_run_id=plan.candidate_input.run_id, requested_rows=len(plan.codes_for(MARKET)),
        calendar=calendar_provenance(), **RESEARCH_FLAGS,
    )


def _record(io, relative, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n').encode()
    io.write_bytes(relative, raw, require_absent=True)
    return dict(path=str(io.root / relative), sha256=sha256(raw).hexdigest())


def _bound_rows(plan, source, batches):
    rows = _project_raw_rows(source.rows, trade_date=plan.trade_date, stage_id=STAGE_ID, market=MARKET)
    finish = {}
    allowed = {_tdx_code(code) for code in plan.codes_for(MARKET)}
    for batch in batches:
        for code in batch['codes']:
            if code in finish or code not in allowed:
                raise ValueError('STAGE7_CAPTURE_BATCH_MEMBERSHIP_INVALID')
            finish[code] = datetime.fromisoformat(batch['finished_at']) if batch['returncode'] == 0 else None
    if set(finish) != allowed:
        raise ValueError('STAGE7_CAPTURE_BATCH_COVERAGE_MISMATCH')
    seen = set()
    for row in rows:
        code = row['code']
        update = datetime.strptime(row['update_time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=SHANGHAI)
        if code in seen or finish.get(code) is None or update >= finish[code]:
            raise ValueError('STAGE7_CAPTURE_ROW_ASOF_OR_MEMBERSHIP_INVALID')
        seen.add(code)
    return rows


def capture(candidate_root, trade_date, expected_current_sha256, *, output_root, shared_root,
            python_path=sys.executable, _clock=None, _process_runner=None, _collector=None):
    """Collect once inside the wall-clock window. Injected runs stay fixtures."""
    plan = prepare_plan(candidate_root, trade_date, expected_current_sha256)
    lower, cutoff = _capture_times(trade_date)
    fixture = any(value is not None for value in (_clock, _process_runner, _collector))
    if fixture and _process_runner is None:
        raise ValueError('STAGE7_CAPTURE_FIXTURE_PROCESS_REQUIRED')
    clock, run = _clock or _now, _process_runner or subprocess.run
    collector = _collector or collect_a_share_hq_minute
    started = _wall(clock)
    identity = _identity(plan)
    output = _private_output(output_root, plan.candidate_input.root, fixture=fixture)
    io = SafeRoot(output)
    prefix = f'{trade_date}/{STAGE_ID}/{MARKET}/{uuid4().hex}'
    batches = []
    attempted = False
    source = None
    rows = []
    failure = None
    raw = None
    finished = None
    source_ref = None
    shared_owner_sha = None
    batch_evidence_invalid = False

    def process(command, **kwargs):
        nonlocal batch_evidence_invalid
        request = json.loads(kwargs['input'])
        if request.get('trade_date') != trade_date or request.get('stage_id') != STAGE_ID:
            raise ValueError('STAGE7_CAPTURE_BATCH_DATE_OR_STAGE_CONFLICT')
        codes = request['codes']
        if not isinstance(codes, list) or not codes or any(not isinstance(code, str) for code in codes):
            raise ValueError('STAGE7_CAPTURE_BATCH_CODES_INVALID')
        request_raw = kwargs['input'].encode()
        relative = f'{prefix}/processes/{len(batches) + 1:03d}'
        io.write_bytes(f'{relative}/request.json', request_raw, require_absent=True)
        begin = _wall(clock)
        if not started <= begin < cutoff:
            raise ValueError('STAGE7_CAPTURE_BATCH_START_OUTSIDE_WINDOW')
        cutoff_budget = (cutoff - begin).total_seconds()
        timeout = min(float(kwargs['timeout']), cutoff_budget)
        kwargs['timeout'] = timeout
        kwargs['env'] = {**kwargs.get('env', os.environ), 'PYTHONDONTWRITEBYTECODE': '1'}
        completed = None
        failure_type = None
        stderr = b''
        try:
            completed = run(command, **kwargs)
            return completed
        except subprocess.TimeoutExpired as error:
            failure_type = 'CUTOFF_BUDGET_TIMEOUT' if timeout == cutoff_budget else 'PROVIDER_TIMEOUT'
            stderr = error.stderr or b''
            raise
        except (OSError, ValueError) as error:
            failure_type = type(error).__name__
            raise
        finally:
            finish = _wall(clock)
            returncode = getattr(completed, 'returncode', None)
            if completed is not None and returncode != 0:
                failure_type = 'PROVIDER_NONZERO_EXIT'
                stderr = completed.stderr or b''
            stderr = stderr.encode() if isinstance(stderr, str) else stderr
            stderr_tail = stderr[-4096:]
            stdout = (completed.stdout or '').encode() if returncode == 0 else b''
            io.write_bytes(f'{relative}/stdout.txt', stdout, require_absent=True)
            batches.append(dict(codes=codes, started_at=begin.isoformat(), finished_at=finish.isoformat(),
                                returncode=returncode, failure_type=failure_type,
                                stderr_bytes=len(stderr), stderr_tail_bytes=len(stderr_tail),
                                stderr_tail_sha256=sha256(stderr_tail).hexdigest() if stderr else None,
                                request_path=str(io.root / relative / 'request.json'),
                                request_sha256=sha256(request_raw).hexdigest(),
                                stdout_path=str(io.root / relative / 'stdout.txt'),
                                stdout_sha256=sha256(stdout).hexdigest(), before_cutoff=begin <= finish < cutoff))
            if not fixture and returncode == 0:
                try:
                    payload = next(line[len(HQ_MARKER):] for line in reversed(stdout.decode().splitlines())
                                   if line.startswith(HQ_MARKER))
                    if any(not row.get('time_key') for row in json.loads(payload)['raw_rows']):
                        batch_evidence_invalid = True
                except (ValueError, KeyError, AttributeError, TypeError, StopIteration):
                    batch_evidence_invalid = True

    if not lower <= started < cutoff:
        failure = 'STAGE7_CAPTURE_WALL_TIME_OUTSIDE_WINDOW'
    else:
        try:
            if not fixture:
                module = _shared_scripts_root(shared_root) / 'scripts/live_acquisition/pytdx_hq.py'
                shared_owner_sha = sha256(module.read_bytes()).hexdigest()
                if shared_owner_sha != VERIFIED_HQ_MODULE_SHA256:
                    raise ValueError('STAGE7_CAPTURE_HQ_OWNER_SHA_MISMATCH')
            attempted = True
            bytecode = sys.dont_write_bytecode
            sys.dont_write_bytecode = True
            try:
                source = collector(plan, codes=plan.codes_for(MARKET), python_path=python_path,
                                   shared_root=shared_root, process_runner=process)
            finally:
                sys.dont_write_bytecode = bytecode
            finished = _wall(clock)
            if batch_evidence_invalid:
                raise ValueError('STAGE7_CAPTURE_HQ_OWNER_TIME_KEY_MISSING')
            if not (started <= finished < cutoff and batches and all(batch['before_cutoff'] for batch in batches)):
                raise ValueError('STAGE7_CAPTURE_PROVIDER_WINDOW_UNVERIFIED')
            if not source.rows:
                process_failures = {batch['failure_type'] for batch in batches if batch['failure_type']}
                detail = ':' + ','.join(sorted(process_failures)) if process_failures else ''
                raise ValueError('STAGE7_CAPTURE_PROVIDER_ROWS_MISSING' + detail)
            if source.source_id != 'pytdx_hq' or source.status not in {'READY', 'PARTIAL_WITH_ROWS'}:
                raise ValueError('STAGE7_CAPTURE_PROVIDER_IDENTITY_INVALID')
            if source.requested_rows != identity['requested_rows']:
                raise ValueError('STAGE7_CAPTURE_PROVIDER_REQUEST_COUNT_MISMATCH')
            rows = _bound_rows(plan, source, batches)
            readback = prepare_plan(candidate_root, trade_date, expected_current_sha256)
            if readback.candidate_input != plan.candidate_input:
                raise ValueError('STAGE7_CAPTURE_CANDIDATE_CHANGED')
            if not fixture:
                source_ref = _record(io, f'{prefix}/process-evidence.json', dict(
                    **identity, capture_started_at=started.isoformat(), capture_finished_at=finished.isoformat(),
                    cutoff_at=cutoff.isoformat(), processes=batches, shared_owner_module_sha256=shared_owner_sha,
                    provider_time_basis=TIME_BASIS, provider_native_timestamp_verified=False,
                ))
                raw = RawStore(output / prefix / 'raw').publish(
                    trade_date=trade_date, stage_id=STAGE_ID, market=MARKET, source_id=source.source_id,
                    source_status='PARTIAL_WITH_ROWS', rows=rows,
                    cannot_confirm=(*source.cannot_confirm, TIME_LIMITATION),
                    source_evidence=(*source.source_evidence, 'publication_scope=ISOLATED_CANDIDATE',
                                     f'candidate_current_sha256={expected_current_sha256}',
                                     f'process_evidence_sha256={source_ref["sha256"]}',
                                     f'process_evidence_path={source_ref["path"]}',
                                     f'provider_time_basis={TIME_BASIS}',
                                     f'capture_started_at={started.isoformat()}', f'capture_finished_at={finished.isoformat()}'),
                    requested_rows=source.requested_rows, missing_symbols=source.missing_symbols,
                    window=STAGE.window, cutoff_at=STAGE.cutoff,
                )
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
            if isinstance(error, subprocess.TimeoutExpired):
                failure = 'STAGE7_CAPTURE_PROCESS_TIMEOUT'
            else:
                failure = str(error)
    completed = _wall(clock)
    status = 'CANNOT_CONFIRM' if failure else 'FIXTURE_PRE_CUTOFF' if fixture else 'CANDIDATE_PRE_CUTOFF'
    receipt = {
        **identity, 'status': status, 'fixture': fixture, 'provider_called': attempted,
        'origin': 'FIXTURE' if fixture else 'MANUAL_ISOLATED_CANDIDATE',
        'capture_started_at': started.isoformat(), 'capture_finished_at': (finished or completed).isoformat(),
        'receipt_prepared_at': completed.isoformat(), 'cutoff_at': cutoff.isoformat(),
        'provider_row_count': len(source.rows) if source is not None else 0,
        'accepted_rows': len(rows) if not failure else 0,
        'last_bar_time': max((row['update_time'] for row in rows), default=None) if not failure else None,
        'window_coverage': 'OBSERVED_ASOF_ONLY',
        'captured_before_cutoff': not failure and not fixture,
        'temporal_cutoff_safe': False,
        'provider_time_basis': TIME_BASIS, 'provider_native_timestamp_verified': False,
        'shared_owner_module_sha256': shared_owner_sha,
        'natural_verified': False, 'formal_pool_ready': False, 'source_status': source.status if source else None,
        'cannot_confirm': [failure] if failure else [*source.cannot_confirm, TIME_LIMITATION],
        'processes': batches, 'process_evidence': source_ref, 'raw': raw,
    }
    return {**receipt, 'receipt': _record(io, f'{prefix}/receipt.json', receipt)}
