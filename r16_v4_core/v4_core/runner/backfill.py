"""Dated replay of the scheduled owners. No scheduler clock, SSE, or natural receipts."""
from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
import fcntl
import json
from functools import lru_cache
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import uuid

from v4_core.config import V4Config
from v4_core.runner.cli import BEIJING, DAILY_WINDOWS, run_a_downstream
from v4_core.runner.dispatch import dispatch_window
from v4_core.runner.evidence import DatedInputs, EvidenceError, FileEvidence, SAFETY_FLAGS, iso_date, require, symbol
from v4_core.runner.owner_inputs import read_owner_inputs
from v4_core.runner.schedule import MAIN_STAGES, at_time, dispatch_evidence_deadline, read_dispatch_inputs
from v4_core.runner.slots import SIX_SLOT_DEFS, run_slot
from v4_core.storage.db import V4Store
from v4_core.runner.state import (WriterBusy, file_identity, heartbeat_record, json_bytes, last_window_record,
                                  publish_bytes, stale_running_reason, writer_lease)

FLAGS = {**SAFETY_FLAGS, 'RESEARCH_ONLY': True, 'execution_mode': 'BACKFILL',
         'natural_window_evidence': False, 'pit_evidence': False}
# 07:00 reads the natural day's live research store; historical replay has no bound equivalent.
_BACKFILL_WINDOWS = {point: workload for point, workload in DAILY_WINDOWS.items()
                     if workload[1] != 'preopen_research'}
# Independent A/HK/stage lanes may still run when another market is missing. Never
# admit a failed prerequisite to a dependent reader (including a standalone rerun).
# The 21:15 owner reads the actual 16:10 A/HK publications, stage7 and fupan;
# 17:30/18:00 cache and 19:00 edition are separate products, not its inputs.
REQUIRES = {'hk_cache_read': ('hk_cache_write',), 'review': ('a_daily',)}


def _env(key):
    return Path(os.environ[key]) if os.environ.get(key) else None


def _scope(cfg, day):
    # Not a second panel or a clone of the natural DB. These are the new results
    # of one requested date; even V4Config.from_env(base) cannot serve this layout.
    base = cfg.base_dir / 'backfill' / day
    require(base.resolve() == cfg.base_dir.resolve() / 'backfill' / day, 'BACKFILL_ROOT_ALIASES_OTHER_PATH')
    return replace(cfg, base_dir=base, db_path=base / 'owner-results.sqlite3', data_dir=base / 'products',
                   bars_dir=base / 'products' / 'bars', logs_dir=base / 'receipts')


def _plan(cfg, day, slot):
    try:
        parsed = date.fromisoformat(day)
    except (ValueError, TypeError) as exc:
        raise EvidenceError('EXPECTED_TRADE_DATE_YYYY_MM_DD') from exc
    require(parsed.isoformat() == day, 'EXPECTED_TRADE_DATE_YYYY_MM_DD')
    require(slot == 'all' or slot in SIX_SLOT_DEFS, 'UNKNOWN_SCHEDULED_SLOT')
    replay = _scope(cfg, day)
    windows = []
    for (h, m), (bound, phase) in _BACKFILL_WINDOWS.items():
        if slot not in ('all', bound):
            continue
        path = replay.logs_dir / 'daily_windows' / f'{day}_{h:02d}{m:02d}.jsonl'
        windows.append(dict(slot_id=bound, phase=phase, window=f'{h:02d}:{m:02d}',
                            backfill_ref=path.relative_to(cfg.base_dir).as_posix()))
    return replay, windows


def _prior(path, row, day):
    try:
        with path.open('rb') as f:
            prior, torn = last_window_record(f)
        require(torn is None and prior and prior.get('trade_date') == day and
                all(prior.get(k) == v for k, v in {**row, **FLAGS}.items()), 'INVALID_BACKFILL_RECEIPT')
        return prior
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {**row, 'schedule_status': 'INVALID_RECEIPT', 'reason': 'INVALID_BACKFILL_RECEIPT'}


def _summary(day, slot, rows, *, status=None, **extra):
    states = {r['schedule_status'] for r in rows}
    if not status:
        if not states or states == {'NOT_FOUND'}:
            status = 'NOT_FOUND'
        elif states == {'DONE'}:
            status = 'DONE'
        elif 'FAILED' in states:
            status = 'FAILED'
        elif states & {'PARTIAL', 'DONE'}:
            status = 'PARTIAL'
        else:
            status = 'CANNOT_CONFIRM'
    return {**FLAGS, 'trade_date': day, 'slot_id': slot, 'status': status, 'windows': rows, **extra}


def _dependencies(cfg, row, known):
    identities = {}
    for phase in REQUIRES.get(row['phase'], ()):
        source = known.get(phase)
        allowed = {'DONE', 'PARTIAL'} if row['phase'] == 'review' and phase == 'a_daily' else {'DONE'}
        require(source and source['schedule_status'] in allowed, f'BACKFILL_PREREQUISITE_NOT_DONE:{phase}')
        ref = source['backfill_ref']
        identities[ref] = sha256((cfg.base_dir / ref).read_bytes()).hexdigest()
    return identities


def _checked_done(cfg, row, known):
    if row['schedule_status'] == 'DONE':
        try:
            deps = _dependencies(cfg, row, known)
            require(all(row.get('upstream_sha256', {}).get(k) == v for k, v in deps.items()),
                    'BACKFILL_PREREQUISITE_CHANGED_FORCE_REQUIRED')
        except (EvidenceError, OSError) as exc:
            return {**row, 'schedule_status': 'CANNOT_CONFIRM', 'stored_status': 'DONE', 'reason': str(exc)}
    return row


def query(cfg, day, slot, *, mode='status'):
    """No mkdir, store constructor, flock, external owner, or executor on this path."""
    require(mode in ('dry-run', 'status'), 'READ_ONLY_QUERY')
    _, windows = _plan(cfg, day, slot)
    wanted = {r['window'] for r in windows}
    known, rows = {}, []
    for r in _plan(cfg, day, 'all')[1]:
        prior = _prior(cfg.base_dir / r['backfill_ref'], r, day) or {**r, 'schedule_status': 'NOT_FOUND'}
        checked = known[r['phase']] = _checked_done(cfg, prior, known)
        if r['window'] in wanted:
            rows.append(checked)
    if mode == 'dry-run':
        inputs, gap = read_dispatch_inputs(_env('V4_R16_INPUT_DIR'), day)
        return _summary(day, slot, rows, status='DRY_RUN', dated_inputs_sha256=inputs.sha256 if inputs else None,
                        inputs_gap=gap, unscheduled_slots=[s for s in SIX_SLOT_DEFS if not any(
                            v[0] == s for v in _BACKFILL_WINDOWS.values()) and slot in ('all', s)])
    return _summary(day, slot, rows)


class _Reads(dict):
    """Consumed SHA records with an attempt-local identity fence, not a source lock."""
    def __init__(self):
        super().__init__()
        self.identities = {}

    def watch(self, path):
        identity = file_identity(path)
        require(self.identities.setdefault(path, identity) == identity, f'BACKFILL_SOURCE_CHANGED:{path}')

    def check(self):
        for path in self.identities:
            self.watch(path)


@dataclass(frozen=True)
class _AuditedInputs(DatedInputs):
    reads: _Reads = field(default_factory=_Reads)

    def file(self, ref):
        path = self.referenced_path(ref)
        owner = self.owner_files.get(ref['path'])
        if owner is None or owner[1] is not None:
            self.reads.watch(path)
        verified = super().file(ref)
        self.reads[verified.path] = verified.sha256
        return verified


def _inputs(day, phase, reads):
    root = _env('V4_R16_INPUT_DIR')
    if root is not None:
        reads.watch(root / day / 'inputs.json')
    inputs, gap = read_dispatch_inputs(root, day)
    if inputs is not None:
        reads['inputs.json'] = inputs.sha256
    else:
        # Missing index is not a corrupt index and is not an HK bars prerequisite.
        require(gap == 'DATED_INPUTS_UNAVAILABLE', gap)
    owner = _env('V4_V35_OWNER_ROOT')
    if owner and phase in {'a_daily', 'evening', 'review'}:
        calendar = _env('V4_A_CALENDAR')
        if calendar is not None and phase in {'evening','review'}:
            reads.watch(calendar)
        inputs = read_owner_inputs(inputs, day, phase, owner, calendar, os.getenv('V4_A_CALENDAR_SHA256'))
    if inputs is None and (phase == 'hk_ingest' or phase == 'source_check' or
                           (phase.startswith('main_') and _env('V4_STAGE_OWNER_ROOT') is not None)):
        return None
    require(inputs is not None, gap)
    return _AuditedInputs(inputs.directory, day, inputs.payload, inputs.sha256, inputs.owner_files, reads)


def _source(inputs, key, env, reads):
    if inputs is not None and key in inputs.payload:
        return inputs.file(inputs.payload[key])
    path = _env(env)
    require(path is not None, f'{key.upper()}_DATED_SOURCE_UNBOUND')
    reads.watch(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EvidenceError(f'{key.upper()}_SOURCE_UNAVAILABLE') from exc
    value = FileEvidence(str(path), sha256(raw).hexdigest(), raw)
    reads[value.path] = value.sha256
    return value


def _derivatives(cfg, replay, inputs, lease, bound):
    day = inputs.trade_date
    selected = _source(inputs, 'selections', 'V4_SELECTIONS_JSON', inputs.reads)
    inputs.reads.watch(cfg.db_path)
    inputs.reads.watch(Path(str(cfg.db_path) + '-wal'))
    if not cfg.db_path.is_file():
        return run_a_downstream(replay, day, lease, bound, selections=selected.data, backfill=True)
    # Feed r17's QFQ reader its actual previous bars/factors. Never copy an
    # authoritative DB or seed a permanent parallel history. One symbol in RAM.
    wal_path = Path(str(cfg.db_path) + '-wal')
    def snapshot_identity():
        wal = file_identity(wal_path)
        require(not wal or wal['size'] == 0, 'BACKFILL_PRIOR_SQLITE_UNCHECKPOINTED_WAL')
        return file_identity(cfg.db_path), wal

    # mode=ro alone can create -wal/-shm. Never checkpoint, create sidecars,
    # or use immutable=1 to overlook a live WAL generation.
    before = snapshot_identity()
    with closing(sqlite3.connect(cfg.db_path.as_uri() + '?mode=ro&immutable=1', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN')
        identity = sha256()

        @lru_cache(maxsize=1)
        def prefix(code, limit):
            rows = conn.execute('''SELECT b.market,b.symbol,b.trade_date,b.open,b.high,b.low,b.close,
                b.volume,b.amount,b.pre_close,f.adj_factor FROM daily_bars b
                LEFT JOIN adj_factors f USING(market,symbol,trade_date)
                WHERE b.market='A' AND b.symbol=? AND b.trade_date<? ORDER BY b.trade_date DESC LIMIT ?''',
                                (code, day, limit)).fetchall()
            records = [dict(r) for r in reversed(rows)]
            identity.update(json_bytes([code, records]))
            return records

        class HistoryReader(V4Store):
            def get_symbol_bars(self, market, symbol, table='qfq_bars', limit=120, *, asof_date=None):
                rows = super().get_symbol_bars(market, symbol, table, limit, asof_date=asof_date)
                if table != 'daily_bars':
                    return rows
                require(market == 'A' and asof_date == day and len(rows) == 1 and rows[0]['trade_date'] == day,
                        'BACKFILL_TARGET_HISTORY_SLICE_UNBOUND')
                return prefix(symbol, limit - 1) + rows

        class Factors(dict):
            def get(self, code, default=None):
                # Same per-symbol r17 lookback as rebuild_qfq_for_date.
                prior = {r['trade_date']: r['adj_factor'] for r in prefix(code, 499) if r['adj_factor'] is not None}
                return {**prior, **super().get(code, {})}

        result = run_a_downstream(replay, day, lease, bound, selections=selected.data,
                                  store=HistoryReader(replay.db_path), factor_map=Factors(bound), backfill=True)
        inputs.reads['prior_A_bars_and_factors_projection'] = identity.hexdigest()
        require(snapshot_identity() == before, 'BACKFILL_PRIOR_SQLITE_CHANGED_DURING_READ')
        return result


def _stage7_reopen(replay, day, phase, inputs, reads):
    """Fence read_stage7's independent DatedInputs; attest only a real READY readback."""
    if phase == 'main_preopen':
        prior = inputs and inputs.payload.get('stage7_prior_source_date')
        if not prior:
            return None
        try:
            day = iso_date(prior)
        except EvidenceError:
            return None  # r17 reports the invalid prior date
    elif phase not in {'main_stage7', 'source_check', 'review'}:
        return None
    registry = replay.data_dir / 'stage_raw' / f'{day}.json'
    if not registry.is_file():
        return None  # first publication consumes the already-audited explicit inputs
    bound = None
    try:
        reads.watch(registry)
        raw = registry.read_bytes()
        record = json.loads(raw)
        root = Path(record['source_root'])
        index = root / day / 'inputs.json'
        reads.watch(index)
        dated = DatedInputs.load(root, day)
        entry = dated.entry('stage7')
        binding = dated.entry_sha256('stage7')
        require(binding == record['source_binding_sha256'], 'STAGE7_INPUT_REGISTRY_SHA_MISMATCH')
        paths = {}
        for role in ('artifact', 'manifest', 'receipt'):
            ref = entry[role]
            path = dated.referenced_path(ref)
            reads.watch(root / day / ref['path'])
            paths[role] = (path, ref)
        bound = {str(registry): sha256(raw).hexdigest(), str(index): dated.sha256, f'{index}#stage7': binding}
    except (OSError, KeyError, TypeError, ValueError):
        pass  # preserve the real owner's missing/invalid component in a partial bundle

    def attest(native):
        if native.get('status') != 'READY':
            return
        require(bound and native.get('registry_sha256') == bound[str(registry)], 'STAGE7_REOPEN_REGISTRY_UNBOUND')
        reads.update(bound)
        for role, (path, ref) in paths.items():
            actual = native['source_identity'][role]
            require((actual['path'], actual['sha256']) == (ref['path'], ref['sha256']), 'STAGE7_REOPEN_SOURCE_UNBOUND')
            reads[str(path)] = actual['sha256']
    return attest


def _dispatch(cfg, replay, start, window, lease, inputs, reads):
    phase = window['phase']
    main = MAIN_STAGES.get((start.hour, start.minute))
    deadline = dispatch_evidence_deadline(start, phase) or start
    if main:
        # r17's stage owner gets a three-minute readback; never wait on a past clock.
        deadline = max(at_time(start, main.tasks[-1].verify_at), start + timedelta(minutes=3))
    stage = _env('V4_STAGE_OWNER_ROOT')
    hk_args = {}
    if phase == 'hk_ingest':
        source = _source(inputs, 'hk_bars', 'V4_HK_BARS_JSON', reads)
        rows = source.json()
        require(isinstance(rows, list) and rows, 'EMPTY_HK_BARS')
        for row in rows:
            require(isinstance(row, dict) and row.get('market', 'HK') == 'HK', 'HK_BARS_MARKET_MISMATCH')
            symbol(row.get('symbol'), 'HK')
        hk_args['hk_bars_data'] = source.data

    def downstream(bound):
        return _derivatives(cfg, replay, inputs, lease, bound)

    attest_stage7 = _stage7_reopen(replay, start.date().isoformat(), phase, inputs, reads)
    status, workload, paired = dispatch_window(
        replay, start, deadline, phase, window['slot_id'], lease, inputs=inputs, inputs_gap='',
        run_slot=lambda *args, **kw: run_slot(*args, **kw, **hk_args), hk_bars_json=None,
        run_a_pipeline=downstream, stage_owner_root=stage)
    if attest_stage7 is not None:
        native = {'source_check': workload, 'main_stage7': paired.get('stage7_formal', {}),
                  'main_preopen': paired.get('stage7_prior', {}),
                  'review': workload.get('detail', {}).get('inputs', {}).get('stage7', {})}
        attest_stage7(native[phase])
    return 'DONE' if status == 'READY' else status, dict(workload=workload, paired_workloads=paired,
                                                         evidence_observed_through=deadline.isoformat())


@contextmanager
def _slot_lock(path, *, existing=False):
    """Same non-blocking flock protocol as r17. Never create a natural journal."""
    if not existing:
        path.parent.mkdir(parents=True, exist_ok=True)
    try:
        file = path.open('rb' if existing else 'a+b')
    except FileNotFoundError:
        if not existing:
            raise
        yield None
        return
    with file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WriterBusy('SLOT_LEASE_HELD') from exc
        yield file


def _writer_observation(path):
    # Probe (but do not hold up the scheduler), never create or edit its lock.
    with _slot_lock(path, existing=True) as handle:
        if handle is None:
            return None
        identity = file_identity(path)
        opened = os.fstat(handle.fileno())
        require(identity and (opened.st_dev, opened.st_ino) == (identity['dev'], identity['ino']),
                'BACKFILL_ORIGINAL_WRITER_CHANGED')
        return identity


def _attempt(cfg, replay, day, window, now, reason, force, lease, known, check_writer):
    path = cfg.base_dir / window['backfill_ref']
    prior = _prior(path, window, day)
    if prior and (prior['schedule_status'] == 'INVALID_RECEIPT' or (prior['schedule_status'] == 'DONE' and not force)):
        return _checked_done(cfg, prior, known)
    start = at_time(datetime.fromisoformat(day).replace(tzinfo=BEIJING), window['window'])
    natural = cfg.logs_dir / 'daily_windows' / path.name
    with _slot_lock(natural, existing=True) as handle, _slot_lock(path.with_suffix('.lock')):
        if handle is not None:
            natural_record, _ = last_window_record(handle)
            if natural_record and natural_record['schedule_status'] == 'RUNNING' and not stale_running_reason(
                    natural_record, cfg.data_dir / 'window_leases' / path.with_suffix('.json').name, now):
                return {**window, 'schedule_status': 'ALREADY_RUNNING', 'reason': 'NATURAL_SLOT_RUNNING'}
        binding = {**FLAGS, **window, 'trade_date': day, 'triggered_at': now.isoformat(), 'reason': reason,
                   'forced': force, 'pid': lease.owner['pid'], 'lease_token': lease.owner['token'],
                   'attempt_id': uuid.uuid4().hex, 'scheduled_for': start.isoformat()}
        def persist(status, **detail):
            event = {**binding, 'schedule_status': status, **detail}
            prefix = path.read_bytes() if path.exists() else b''
            publish_bytes(path, prefix + json_bytes(event), lease=lease)
            return event

        if prior and prior['schedule_status'] == 'RUNNING':
            stale = stale_running_reason(prior, replay.data_dir / 'window_leases' / path.with_suffix('.json').name, now)
            if not stale:
                return {**window, 'schedule_status': 'ALREADY_RUNNING'}
            persist('STALE_RUNNING_RECOVERED', stale_reason=stale, stale_pid=prior.get('pid'),
                    stale_attempt_id=prior.get('attempt_id'), stale_lease_token=prior.get('lease_token'))
        persist('RUNNING', **heartbeat_record(now))
        reads = _Reads()
        try:
            check_writer()
            reads.update(_dependencies(cfg, window, known))
            inputs = _inputs(day, window['phase'], reads)
            status, details = _dispatch(cfg, replay, start, window, lease, inputs, reads)
            reads.check()
            check_writer()
        except EvidenceError as exc:
            status, details = 'CANNOT_CONFIRM', {'workload': {'status': 'CANNOT_CONFIRM', 'reason': str(exc)}}
        except Exception as exc:
            status, details = 'FAILED', {'error': str(exc), 'error_type': type(exc).__name__}
        return persist(status, upstream_sha256=reads, dated_inputs_sha256=reads.get('inputs.json'), **details)


def rerun(cfg, day, slot, *, mode='dry-run', reason='', force=False):
    require(mode in ('dry-run', 'execute'), 'UNKNOWN_BACKFILL_MODE')
    reason = reason.strip()
    require(not force or reason, 'FORCE_REQUIRES_AUDIT_REASON')
    if mode == 'dry-run':
        return query(cfg, day, slot, mode=mode)
    replay, windows = _plan(cfg, day, slot)
    now = datetime.now(BEIJING)
    require(day < now.date().isoformat(), 'BACKFILL_REQUIRES_HISTORICAL_DATE')
    if not windows:
        return _summary(day, slot, [], status='CANNOT_CONFIRM', reason='NO_BOUND_R17_SCHEDULED_WINDOW')
    # A result path redirected into natural storage defeats a mode label. Inspect
    # only this date's result namespace; never traverse a symlink or canonical DB.
    for parent, dirs, files in os.walk(replay.base_dir, followlinks=False):
        for name in dirs:
            require(not (Path(parent) / name).is_symlink(), 'BACKFILL_DIRECTORY_ALIAS')
        for name in files:
            item = Path(parent) / name
            require(not item.is_symlink() and item.is_file() and item.stat().st_nlink == 1, 'BACKFILL_FILE_ALIAS')
    # No replay metadata belongs in the original namespace. An absent natural
    # lock cannot be held without creating it; observe its generation on both
    # sides of dispatch and fail closed on the transition, not on a made-up lock.
    lock_path = cfg.data_dir / '.r16-writer.lock'
    try:
        original = _writer_observation(lock_path)
        previous = query(cfg, day, slot)
        if not force and all(r.get('stored_status', r['schedule_status']) == 'DONE' for r in previous['windows']):
            return previous

        def check_writer():
            try:
                require(_writer_observation(lock_path) == original, 'BACKFILL_ORIGINAL_WRITER_CHANGED')
            except WriterBusy as exc:
                raise EvidenceError('BACKFILL_ORIGINAL_WRITER_CHANGED_OR_BUSY') from exc

        with writer_lease(replay.data_dir, replay.logs_dir, f'BACKFILL/{day}/{slot}') as lease:
            known = {r['phase']: r for r in query(cfg, day, 'all')['windows']}
            rows = []
            for window in windows:
                try:
                    result = _attempt(cfg, replay, day, window, now, reason, force, lease, known, check_writer)
                except WriterBusy as exc:
                    result = {**window, 'schedule_status': 'ALREADY_RUNNING', 'reason': str(exc)}
                known[window['phase']] = result
                rows.append(result)
            return _summary(day, slot, rows)
    except WriterBusy as exc:
        return _summary(day, slot, [], status='WRITER_BUSY', reason=str(exc))
