"""Bounded, evidence-led next-session research plans; no fetches or trading writes.

The calendar is the existing V3.5 HK-securities calendar, not the A-share or
Connect calendar. Price references are read only through the existing native
CloseSnapshotStore, and missing units/session/basis stay UNKNOWN.
"""
from __future__ import annotations
from datetime import datetime, time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping
from .workspace_projection import FLAGS, HK, canonical_symbol, date_token, digest, timestamp


def plan_context(date: str, *, now: datetime | None = None) -> dict:
    from contracts.trading_calendar import (CALENDAR_PATH, load_market_calendar,
        resolve_market_states, TradingDayState)
    target = datetime.strptime(date_token(date), '%Y%m%d').date()
    cutoff = now if now is not None else datetime.now(timezone.utc)
    if cutoff.tzinfo is None:
        raise ValueError('PLAN_CUTOFF_MUST_HAVE_TIMEZONE')
    cutoff = cutoff.astimezone(HK)
    calendar = load_market_calendar()
    if resolve_market_states(calendar, date)['hk_securities'] not in {
        TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM}:
        raise ValueError('PLAN_TARGET_NOT_VERIFIED_HK_TRADING_SESSION')
    # A preopen/review plan uses no price from the target session itself. The
    # price baseline below remains the most recent completed full session;
    # the publication window is derived separately from the two most recent
    # completed HK securities sessions, including a native half-day close.
    market = calendar.markets['hk_securities']
    cursor = min(target - timedelta(days=1), cutoff.date())
    close_hhmm = str(market['full_day_close'])

    def session_close(session_date, state):
        if state == TradingDayState.FULL_TRADING_DAY:
            hhmm = close_hhmm
        elif state == TradingDayState.HALF_TRADING_DAY_AM:
            hhmm = market.get('half_day_close')
            if hhmm is None:
                raise ValueError('PLAN_HALF_DAY_CLOSE_UNAVAILABLE')
            hhmm = str(hhmm)
        else:
            return None
        if len(hhmm) != 4 or not hhmm.isdigit():
            raise ValueError('PLAN_SESSION_CLOSE_INVALID_NATIVE_CALENDAR')
        try:
            close_time = time(int(hhmm[:2]), int(hhmm[2:]))
        except ValueError as error:
            raise ValueError('PLAN_SESSION_CLOSE_INVALID_NATIVE_CALENDAR') from error
        return datetime.combine(session_date, close_time, HK)

    while cursor.year == calendar.year:
        key = cursor.strftime('%Y%m%d')
        state = resolve_market_states(calendar, key)['hk_securities']
        close = session_close(cursor, state)
        if state == TradingDayState.FULL_TRADING_DAY and close <= cutoff:
            break
        cursor -= timedelta(days=1)
    else:
        raise ValueError('PLAN_COMPLETED_HK_SESSION_OUTSIDE_NATIVE_CALENDAR')

    # The focus window begins at the close of the older of the two most
    # recent completed HK sessions before the plan date. Completion is proved
    # by that session's own native full/half-day close, never by a guessed
    # clock time. This keeps the price baseline above independent from the
    # publication window while rolling across weekends and holidays.
    session_cursor = min(target - timedelta(days=1), cutoff.date())
    completed_sessions = []
    while session_cursor.year == calendar.year and len(completed_sessions) < 2:
        session_key = session_cursor.strftime('%Y%m%d')
        session_state = resolve_market_states(calendar, session_key)['hk_securities']
        session_finish = session_close(session_cursor, session_state)
        if (session_state in {TradingDayState.FULL_TRADING_DAY,
                              TradingDayState.HALF_TRADING_DAY_AM}
                and session_finish <= cutoff):
            completed_sessions.append((session_cursor, session_finish))
        session_cursor -= timedelta(days=1)
    if len(completed_sessions) != 2:
        raise ValueError('PLAN_TWO_COMPLETED_HK_SESSIONS_UNAVAILABLE')
    focus_date, focus_close = completed_sessions[-1]
    first = focus_date
    end = min(target, cutoff.date())
    if (end-first).days > 30:
        raise ValueError('PLAN_SOURCE_WINDOW_EXCEEDS_31_DAY_BOUND')
    dates = [(first+timedelta(days=i)).strftime('%Y%m%d') for i in range((end-first).days+1)]
    return dict(plan_trade_date=date, research_cutoff=cutoff.isoformat(), market_session=key,
        market_session_close=close.isoformat(), price_session_status='EXPECTED_COMPLETED_SESSION_NOT_QUOTE_VERIFICATION',
        focus_window_start=focus_close.isoformat(),
        focus_window_basis='TWO_COMPLETED_HK_SESSIONS_POST_CLOSE_WINDOW',
        source_dates=dates, calendar_owner='contracts.trading_calendar / hk_securities',
        calendar_sha256=hashlib.sha256(CALENDAR_PATH.read_bytes()).hexdigest(),
        observation_phase='PREOPEN_PLAN' if cutoff < datetime.combine(target,
            datetime.strptime(calendar.markets['hk_securities']['full_day_sessions'][0]['start'],'%H%M').time(),HK) else 'AS_OF_RESEARCH_REVIEW',
        market_data_verified=False, us_market_session=None, us_market_coverage='NOT_VERIFIED', **FLAGS)


def screen_context(context: Mapping[str, Any]) -> dict:
    """Resolve a completed full HK session for this selection-day screen.

    Planning close references and prior-session membership keep the original
    plan_context. Only the screen may advance to the selection day after its
    native close. A half day does not supply a full-day volume comparison.
    Owner availability is checked separately when the selected panel is read.
    """
    from contracts.trading_calendar import (CALENDAR_PATH, load_market_calendar,
        resolve_market_states, TradingDayState)
    cutoff = timestamp(context.get('research_cutoff'))
    if cutoff is None:
        raise ValueError('SCREEN_RESEARCH_CUTOFF_UNVERIFIED')
    target_key = date_token(str(context.get('plan_trade_date') or ''))
    target = datetime.strptime(target_key, '%Y%m%d').date()
    calendar_bytes = CALENDAR_PATH.read_bytes()
    calendar = load_market_calendar()
    market = calendar.markets['hk_securities']
    target_state = resolve_market_states(calendar, target_key)['hk_securities']
    if target_state not in {TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM}:
        raise ValueError('SCREEN_TARGET_NOT_VERIFIED_HK_TRADING_SESSION')

    def native_time(day, value):
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}', value):
            raise ValueError('SCREEN_NATIVE_SESSION_TIME_INVALID')
        try:
            return datetime.combine(day, time(int(value[:2]), int(value[2:])), HK)
        except ValueError as exc:
            raise ValueError('SCREEN_NATIVE_SESSION_TIME_INVALID') from exc

    half_day = target_state == TradingDayState.HALF_TRADING_DAY_AM
    target_open = native_time(target, market['half_day_sessions' if half_day else 'full_day_sessions'][0]['start'])
    target_close = native_time(target, market['half_day_close' if half_day else 'full_day_close'])
    phase = ('PREOPEN_COMPLETED_SESSION' if cutoff < target_open else
             'INTRADAY_COMPLETED_SESSION' if cutoff < target_close else 'POST_CLOSE_COMPLETED_SESSION')
    cursor = min(target, cutoff.date())
    while cursor.year == calendar.year:
        session = cursor.strftime('%Y%m%d')
        state = resolve_market_states(calendar, session)['hk_securities']
        if state == TradingDayState.FULL_TRADING_DAY:
            session_close = native_time(cursor, market['full_day_close'])
            if session_close <= cutoff:
                break
        cursor -= timedelta(days=1)
    else:
        raise ValueError('SCREEN_COMPLETED_HK_SESSION_OUTSIDE_NATIVE_CALENDAR')
    if CALENDAR_PATH.read_bytes() != calendar_bytes:
        raise ValueError('SCREEN_CALENDAR_CHANGED_DURING_READ')
    return dict(context,
        planning_market_session=context.get('planning_market_session', context.get('market_session')),
        market_session=session, market_session_close=session_close.isoformat(),
        screen_target_trade_date=target_key, screen_phase=phase,
        screen_session_policy='COMPLETED_FULL_HK_SECURITIES_SESSION',
        screen_calendar_sha256=hashlib.sha256(calendar_bytes).hexdigest(),
        screen_session_status='EXPECTED_COMPLETED_SESSION_NOT_DATA_VERIFICATION')


def _screen_data_context(context: Mapping[str, Any]) -> dict:
    return {key: context.get(key) for key in (
        'plan_trade_date', 'planning_market_session', 'market_session', 'market_session_close',
        'screen_target_trade_date', 'screen_phase', 'screen_session_policy',
        'screen_calendar_sha256', 'screen_session_status', 'research_cutoff')}


def temporal_role(material: Mapping[str, Any], context: Mapping[str, Any]) -> str:
    cutoff=timestamp(context.get('research_cutoff'))
    from .announcement_materials import is_mirror, mirror_role
    if is_mirror(material):
        return mirror_role(material,timestamp(context.get('focus_window_start')),cutoff)
    if cutoff is None:
        return 'TIME_CONTEXT_UNVERIFIED'
    for key in ('published_at','available_at','retrieved_at','collected_at','first_seen_at','archive_recorded_at'):
        value=timestamp(material.get(key))
        if value and value>cutoff:
            return 'AFTER_CUTOFF_EXCLUDED'
    published=timestamp(material.get('published_at'))
    if published is None:
        return 'PUBLICATION_UNKNOWN'
    start=timestamp(context.get('focus_window_start'))
    return 'NEW_PLAN_PUBLICATION' if start and published>=start else 'BACKGROUND'


def _number(value: Any, *, positive: bool = True) -> float | None:
    if isinstance(value,bool):
        return None
    try:
        n=float(value)
    except (TypeError,ValueError,OverflowError):
        return None
    return n if math.isfinite(n) and (n>0 if positive else n>=0) else None


def verified_quote(quote: Mapping[str, Any] | None, symbol: str, context: Mapping[str, Any]) -> dict | None:
    if not isinstance(quote,Mapping):
        return None
    refs=quote.get('source_refs')
    if (quote.get('verification')!='OWNER_VERIFIED' or quote.get('symbol')!=symbol
            or quote.get('session_date')!=context.get('market_session') or quote.get('currency')!='HKD'
            or quote.get('session_kind')!='FULL_DAY_CLOSE' or quote.get('price_basis') not in {'RAW','UNADJUSTED'}
            or not isinstance(refs,list) or not refs or any(not isinstance(r,Mapping) or
                not re.fullmatch(r'[0-9a-f]{64}', str(r.get('payload_sha256',''))) for r in refs)
            or _number(quote.get('close')) is None):
        return None
    value=dict(quote)
    for k in ('open','high','low','close','pre_close','amount'):
        value[k]=_number(quote.get(k),positive=k!='amount')
    if value['low'] is not None and value['low']>value['close']:
        return None
    if value['high'] is not None and value['high']<value['close']:
        return None
    return value


def _read_hk02_panel_witness(authority_root: Path | None, day: str, *,
                             research_cutoff: str | None = None,
                             required_history_date: str | None = None) -> tuple[dict | None, list[str]]:
    """Read the existing owner's immutable exact-date panel, never later prices.

    The original owner's panel_latest pointer may identify a same-target
    correction whose directory also records the history date it repaired.
    Read that pointer before the older YYYYMMDD-<sha12> directory, but use the
    pointer's revision only when its manifest and panel verify and its
    manifest-prepared time is no later than the plan cutoff. Earlier plans may
    use the one immutable exact-date revision that was already available then.
    Multiple exact-date revisions stay ambiguous; mtime is never a selector.
    """
    if authority_root is None:
        return None, ['PLAN_HK_02_PANEL_AUTHORITY_ROOT_NOT_BOUND']
    try:
        import os
        import stat
        from infrastructure.owned_io import SafeRoot
        from .workspace_read_control import checkpoint, count
        if not re.fullmatch(r'\d{8}', day):
            return None, ['PLAN_HK_02_EXACT_DATE_INVALID']
        cutoff = None
        if research_cutoff is not None:
            cutoff = timestamp(research_cutoff)
            if cutoff is None:
                return None, ['PLAN_HK_02_RESEARCH_CUTOFF_INVALID']
        if (required_history_date is not None
                and (not re.fullmatch(r'\d{8}', required_history_date)
                     or required_history_date >= day)):
            return None, ['PLAN_HK_02_HISTORY_REQUIRED_DATE_INVALID']
        root = Path(authority_root).expanduser().absolute()
        asset_root = root / 'assets' / 'hk_0_2'
        io = SafeRoot(asset_root)
        candidates = []
        same_day_directories = []
        try:
            with io.directory('panels') as fd:
                with os.scandir(fd) as entries:
                    for index, entry in enumerate(entries):
                        if index >= 4096:
                            return None, ['PLAN_HK_02_PANEL_DIRECTORY_BOUND_EXCEEDED']
                        if entry.name.startswith(day+'-'):
                            if not entry.is_dir(follow_symlinks=False):
                                return None, ['PLAN_HK_02_PANEL_PATH_UNSAFE']
                            relative = 'panels/'+entry.name+'/manifest.json'
                            same_day_directories.append(relative)
                            if re.fullmatch(day+r'-[0-9a-f]{12}', entry.name):
                                candidates.append(relative)
        except FileNotFoundError:
            pass
        candidates.sort()
        same_day_directories.sort()
        if required_history_date is None and len(candidates)>1:
            return None, ['PLAN_HK_02_EXACT_DATE_PANEL_AMBIGUOUS']
        legacy_contract = 'tdx_vipdoc_71_day+verified_zero_trade_repairs'
        recovered_contract = legacy_contract+'+futu_history_gapfill'

        def verified_manifest(relative_manifest: str, resolution: str) -> tuple[dict | None, list[str]]:
            if not re.fullmatch(r'panels/[A-Za-z0-9._-]+/manifest\.json', relative_manifest):
                return None, ['PLAN_HK_02_PANEL_PATH_UNSAFE']
            if not Path(relative_manifest).parent.name.startswith(day+'-'):
                return None, ['PLAN_HK_02_PANEL_PATH_DATE_MISMATCH']
            raw_manifest = io.read_bytes(relative_manifest, max_bytes=1024*1024)
            manifest = json.loads(raw_manifest)
            if not isinstance(manifest, Mapping) or str(manifest.get('panel_max_date') or '') != day:
                return None, ['PLAN_HK_02_PANEL_TARGET_MISMATCH']
            source_contract = manifest.get('source_contract')
            if (manifest.get('asset_schema_version') != 'v3_shared_data.hk_0_2_panel_asset.v2'
                    or source_contract not in {legacy_contract, recovered_contract}
                    or manifest.get('research_only') is not True
                    or manifest.get('production_allowed') is not False
                    or manifest.get('buy_gate_updated') is not False
                    or manifest.get('orders_sent') is not False):
                return None, ['PLAN_HK_02_PANEL_AUTHORITY_CONTRACT_INVALID']
            if source_contract == recovered_contract:
                recovery = manifest.get('history_recovery')
                prepared_at = timestamp(manifest.get('manifest_prepared_at'))
                received_at = timestamp(recovery.get('received_at')) if isinstance(recovery, Mapping) else None
                requested_at = timestamp(recovery.get('requested_at')) if isinstance(recovery, Mapping) else None
                inputs = recovery.get('source_input_sha256') if isinstance(recovery, Mapping) else None
                new_dates = manifest.get('new_dates')
                new_row_count = manifest.get('new_row_count')
                source_date = str(recovery.get('source_date') or '') if isinstance(recovery, Mapping) else ''
                if (not isinstance(recovery, Mapping)
                        or recovery.get('schema_version') != 'v4.hk_history_price_recovery.v1'
                        or not re.fullmatch(r'\d{8}', source_date)
                        or not source_date < day
                        or type(recovery.get('row_count')) is not int
                        or type(recovery.get('requested_code_count')) is not int
                        or recovery.get('row_count') != recovery.get('requested_code_count')
                        or type(new_row_count) is not int or new_row_count != recovery.get('row_count')
                        or not isinstance(new_dates, list) or not new_dates
                        or any(not isinstance(value, str) or not re.fullmatch(r'\d{8}', value)
                               or value >= day for value in new_dates)
                        or len(set(new_dates)) != len(new_dates) or source_date not in new_dates
                        or recovery.get('coverage_rate') != 1.0
                        or recovery.get('provider') != 'MIXED_PYTDX_HQ_DAILY_AND_FUTU_OPEND_HISTORY_KLINE'
                        or recovery.get('adjustment') != 'NONE'
                        or recovery.get('natural_verified') is not False
                        or recovery.get('production_allowed') is not False
                        or recovery.get('buy_gate_updated') is not False
                        or recovery.get('orders_sent') is not False
                        or not re.fullmatch(r'[0-9a-f]{64}', str(recovery.get('source_sha256') or ''))
                        or not isinstance(inputs, Mapping) or not inputs
                        or any(not re.fullmatch(r'[0-9a-f]{64}', str(value)) for value in inputs.values())
                        or not re.fullmatch(r'[0-9a-f]{64}', str(manifest.get('parent_panel_sha256') or ''))
                        or prepared_at is None or received_at is None or requested_at is None
                        or requested_at > received_at or received_at > prepared_at):
                    return None, ['PLAN_HK_02_PANEL_RECOVERY_LINEAGE_INVALID']
            relative_panel = str(manifest.get('panel_relative') or '')
            expected_panel = str(Path(relative_manifest).parent/'hkconnect_vipdoc_daily_panel.parquet')
            if relative_panel != expected_panel:
                return None, ['PLAN_HK_02_PANEL_PATH_MISMATCH']
            prepared_at = timestamp(manifest.get('manifest_prepared_at'))
            if prepared_at is None and cutoff is not None:
                return None, ['PLAN_HK_02_PANEL_AVAILABLE_AT_UNVERIFIED']
            # Hash bounded streaming bytes through the original O_NOFOLLOW boundary.
            sha = hashlib.sha256()
            total = 0
            with io.parent(relative_panel) as (parent, name):
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    meta = os.fstat(fd)
                    if not stat.S_ISREG(meta.st_mode) or meta.st_size > 512*1024*1024:
                        return None, ['PLAN_HK_02_PANEL_BYTES_BOUND_OR_TYPE_INVALID']
                    with os.fdopen(fd, 'rb', closefd=False) as handle:
                        while chunk := handle.read(1024*1024):
                            checkpoint(); total += len(chunk)
                            if total > 512*1024*1024:
                                return None, ['PLAN_HK_02_PANEL_BYTES_BOUND_OR_TYPE_INVALID']
                            sha.update(chunk)
                    after = os.fstat(fd)
                    if (meta.st_size, meta.st_mtime_ns, meta.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                        return None, ['PLAN_HK_02_PANEL_CHANGED_DURING_READ']
                finally:
                    os.close(fd)
            panel_sha = sha.hexdigest()
            count('panel_bytes_hashed', total)
            if panel_sha != str(manifest.get('panel_sha256') or ''):
                return None, ['PLAN_HK_02_PANEL_AUTHORITY_CHECKSUM_MISMATCH']
            if not Path(relative_manifest).parent.name.endswith('-'+panel_sha[:12]):
                return None, ['PLAN_HK_02_PANEL_SHA_PATH_MISMATCH']
            if io.read_bytes(relative_manifest, max_bytes=1024*1024) != raw_manifest:
                return None, ['PLAN_HK_02_MANIFEST_CHANGED_DURING_READ']
            return dict(owner='V4_SHARED_HK_0_2_PANEL_AUTHORITY',
                panel_manifest_path=str(asset_root/relative_manifest),
                panel_manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
                panel_path=str(asset_root/relative_panel), panel_sha256=panel_sha,
                panel_max_date=day, panel_code_count=manifest.get('panel_code_count'),
                panel_rows=manifest.get('panel_rows'), source_contract=source_contract,
                panel_available_at=(manifest.get('manifest_prepared_at') if prepared_at else None),
                history_source_date=(manifest.get('history_recovery').get('source_date')
                    if isinstance(manifest.get('history_recovery'), Mapping) else None),
                history_parent_panel_sha256=(manifest.get('parent_panel_sha256')
                    if isinstance(manifest.get('history_recovery'), Mapping) else None),
                price_currency='HKD', price_basis='RAW', session_kind='FULL_DAY_CLOSE', amount_unit='HKD',
                resolution=resolution, semantics='RAW_HK_0_2_VIPDOC_DAILY_PANEL_NO_ADJUSTMENT'), []

        exact_relative = candidates[0] if candidates else None

        def resolve_required_history() -> tuple[dict | None, list[str]]:
            """Select a verified same-target recovery for the requested history session."""
            legacy_candidates = []
            recovered_candidates = []
            classified_manifest_sha256 = {}
            for relative in same_day_directories:
                raw = io.read_bytes(relative, max_bytes=1024*1024)
                manifest = json.loads(raw)
                if not isinstance(manifest, Mapping) or str(manifest.get('panel_max_date') or '') != day:
                    return None, ['PLAN_HK_02_PANEL_TARGET_MISMATCH']
                contract = manifest.get('source_contract')
                if contract == legacy_contract:
                    legacy_candidates.append(relative)
                elif contract == recovered_contract:
                    recovered_candidates.append(relative)
                else:
                    return None, ['PLAN_HK_02_PANEL_AUTHORITY_CONTRACT_INVALID']
                classified_manifest_sha256[relative] = hashlib.sha256(raw).hexdigest()
            if len(legacy_candidates) > 1:
                return None, ['PLAN_HK_02_EXACT_DATE_PANEL_AMBIGUOUS']

            base_witness = None
            base_before_cutoff = True
            base_available_at = None
            base_relative = legacy_candidates[0] if legacy_candidates else None
            if base_relative is not None:
                base_witness, base_gaps = verified_manifest(
                    base_relative, 'EXACT_DATE_IMMUTABLE_OWNER_ASSET')
                if base_witness is None:
                    return None, base_gaps
                if base_witness.get('panel_manifest_sha256') != classified_manifest_sha256[base_relative]:
                    return None, ['PLAN_HK_02_MANIFEST_CHANGED_DURING_READ']
                base_available_at = timestamp(base_witness.get('panel_available_at'))
                if cutoff is not None and base_available_at is None:
                    return None, ['PLAN_HK_02_PANEL_AVAILABLE_AT_UNVERIFIED']
                if cutoff is not None and base_available_at > cutoff:
                    base_before_cutoff = False

            eligible_recoveries = []
            future_matching_recovery = False
            future_other_history = False
            for recovery_relative in recovered_candidates:
                recovery_witness, recovery_gaps = verified_manifest(
                    recovery_relative, 'SAME_DATE_HISTORY_RECOVERY_IMMUTABLE_OWNER_ASSET')
                if recovery_witness is None:
                    return None, recovery_gaps
                if (recovery_witness.get('source_contract') != recovered_contract
                        or recovery_witness.get('panel_manifest_sha256')
                        != classified_manifest_sha256[recovery_relative]):
                    return None, ['PLAN_HK_02_MANIFEST_CHANGED_DURING_READ']
                recovery_available_at = timestamp(recovery_witness.get('panel_available_at'))
                if cutoff is not None and recovery_available_at is None:
                    return None, ['PLAN_HK_02_PANEL_AVAILABLE_AT_UNVERIFIED']
                is_before_cutoff = cutoff is None or recovery_available_at <= cutoff
                matches_history = recovery_witness.get('history_source_date') == required_history_date
                if not matches_history:
                    if is_before_cutoff:
                        return None, ['PLAN_HK_02_PANEL_RECOVERY_SESSION_MISMATCH']
                    future_other_history = True
                    continue
                if base_witness is None:
                    return None, ['PLAN_HK_02_PANEL_RECOVERY_PARENT_UNVERIFIED']
                if (base_witness.get('source_contract') != legacy_contract
                        or recovery_witness.get('history_parent_panel_sha256')
                        != base_witness.get('panel_sha256')):
                    return None, ['PLAN_HK_02_PANEL_RECOVERY_PARENT_MISMATCH']
                if (base_available_at is not None and recovery_available_at is not None
                        and recovery_available_at < base_available_at):
                    return None, ['PLAN_HK_02_PANEL_RECOVERY_AVAILABILITY_INVALID']
                if matches_history and not is_before_cutoff:
                    future_matching_recovery = True
                elif matches_history:
                    eligible_recoveries.append(recovery_witness)

            if len(eligible_recoveries) > 1:
                return None, ['PLAN_HK_02_PANEL_RECOVERY_AMBIGUOUS']
            if eligible_recoveries:
                return eligible_recoveries[0], []
            # An as-of query before the recovery existed keeps the exact base
            # revision. This preserves historical point-in-time behavior.
            if future_matching_recovery and base_witness is not None and base_before_cutoff:
                base_witness['resolution'] = 'EXACT_DATE_IMMUTABLE_OWNER_ASSET_BEFORE_CUTOFF'
                return base_witness, []
            if base_witness is not None and base_before_cutoff:
                return base_witness, []
            if base_relative is None and not future_other_history:
                return None, ['PLAN_HK_02_EXACT_DATE_PANEL_MISSING']
            return None, ['PLAN_HK_02_PANEL_AFTER_RESEARCH_CUTOFF']

        pointer_missing = False
        try:
            pointer = json.loads(io.read_bytes('panel_latest.json', max_bytes=1024*1024))
        except FileNotFoundError:
            pointer_missing = True
            pointer = None
        except (ValueError, TypeError):
            return None, ['PLAN_HK_02_PANEL_LATEST_POINTER_INVALID']
        if not pointer_missing:
            if not isinstance(pointer, Mapping):
                return None, ['PLAN_HK_02_PANEL_LATEST_POINTER_INVALID']
            relative_manifest = str(pointer.get('manifest_relative') or '')
            if not re.fullmatch(r'panels/[A-Za-z0-9._-]+/manifest\.json', relative_manifest):
                return None, ['PLAN_HK_02_PANEL_LATEST_POINTER_INVALID']
            try:
                pointed_raw = io.read_bytes(relative_manifest, max_bytes=1024*1024)
                pointed_manifest = json.loads(pointed_raw)
            except (FileNotFoundError, ValueError, TypeError):
                return None, ['PLAN_HK_02_PANEL_LATEST_MANIFEST_UNREADABLE']
            if not isinstance(pointed_manifest, Mapping):
                return None, ['PLAN_HK_02_PANEL_LATEST_MANIFEST_INVALID']
            if required_history_date is not None:
                # Historical rebound plans are keyed by their exact target
                # date, while panel_latest can have moved to a later trading
                # date. Resolve only an immutable same-target revision whose
                # verified recovery manifest names the calendar-required
                # history session and whose parent digest matches the exact
                # legacy target panel. The pointer is still parsed and path
                # bounded above, but it is not a historical revision index.
                if str(pointed_manifest.get('panel_max_date') or '') == day:
                    pointed_witness, pointed_gaps = verified_manifest(
                        relative_manifest, 'PANEL_LATEST_TARGET_OWNER_ASSET')
                    if pointed_witness is None:
                        return None, pointed_gaps
                    if hashlib.sha256(pointed_raw).hexdigest() != pointed_witness.get('panel_manifest_sha256'):
                        return None, ['PLAN_HK_02_MANIFEST_CHANGED_DURING_READ']
                return resolve_required_history()
            if str(pointed_manifest.get('panel_max_date') or '') == day:
                witness, gaps = verified_manifest(relative_manifest, 'PANEL_LATEST_TARGET_OWNER_ASSET')
                if witness is None:
                    return None, gaps
                if hashlib.sha256(pointed_raw).hexdigest() != witness.get('panel_manifest_sha256'):
                    return None, ['PLAN_HK_02_MANIFEST_CHANGED_DURING_READ']
                available_at = timestamp(witness.get('panel_available_at'))
                if cutoff is not None and available_at is None:
                    return None, ['PLAN_HK_02_PANEL_AVAILABLE_AT_UNVERIFIED']
                if cutoff is not None and available_at > cutoff:
                    if exact_relative is None:
                        return None, ['PLAN_HK_02_PANEL_AFTER_RESEARCH_CUTOFF']
                    witness, gaps = verified_manifest(exact_relative, 'EXACT_DATE_IMMUTABLE_OWNER_ASSET')
                    if witness is None:
                        return None, gaps
                    exact_available_at = timestamp(witness.get('panel_available_at'))
                    if exact_available_at is None:
                        return None, ['PLAN_HK_02_PANEL_AVAILABLE_AT_UNVERIFIED']
                    if exact_available_at > cutoff:
                        return None, ['PLAN_HK_02_PANEL_AFTER_RESEARCH_CUTOFF']
                    witness['resolution'] = 'EXACT_DATE_IMMUTABLE_OWNER_ASSET_BEFORE_CUTOFF'
                    return witness, []
                if witness.get('source_contract') == recovered_contract:
                    recovery = pointed_manifest.get('history_recovery')
                    declared_parent_sha = str(pointed_manifest.get('parent_panel_sha256') or '')
                    if (exact_relative is None or relative_manifest == exact_relative
                            or not isinstance(recovery, Mapping)
                            or not re.fullmatch(r'[0-9a-f]{64}', declared_parent_sha)):
                        return None, ['PLAN_HK_02_PANEL_RECOVERY_PARENT_UNVERIFIED']
                    parent_witness, parent_gaps = verified_manifest(
                        exact_relative, 'EXACT_DATE_IMMUTABLE_OWNER_ASSET')
                    if parent_witness is None:
                        return None, parent_gaps
                    if (parent_witness.get('source_contract') != legacy_contract
                            or parent_witness.get('panel_sha256') != declared_parent_sha):
                        return None, ['PLAN_HK_02_PANEL_RECOVERY_PARENT_MISMATCH']
                return witness, []
        if required_history_date is not None:
            return resolve_required_history()
        if exact_relative is not None:
            witness, gaps = verified_manifest(exact_relative, 'EXACT_DATE_IMMUTABLE_OWNER_ASSET')
            if witness is None:
                return None, gaps
            available_at = timestamp(witness.get('panel_available_at'))
            if cutoff is not None and available_at is None:
                return None, ['PLAN_HK_02_PANEL_AVAILABLE_AT_UNVERIFIED']
            if cutoff is not None and available_at > cutoff:
                return None, ['PLAN_HK_02_PANEL_AFTER_RESEARCH_CUTOFF']
            return witness, []
        if not pointer_missing:
            return None, ['PLAN_HK_02_EXACT_DATE_PANEL_MISSING', 'PLAN_HK_02_PANEL_TARGET_MISMATCH']
        return None, ['PLAN_HK_02_EXACT_DATE_PANEL_MISSING']
    except (OSError, ValueError, KeyError, TypeError):
        return None, ['PLAN_HK_02_PANEL_AUTHORITY_READ_FAILED']


REBOUND_SCREEN_SCHEMA = 'v4.manager_research.rebound_v3_screen.v1'
REBOUND_SCREEN_RULE = '20260923_REBOUND_TWO_GATE_V1'
_REBOUND_OVERSOLD_RATIO = 0.8
_REBOUND_AMOUNT_MIN = 100_000_000.0
_REBOUND_AMOUNT_MAX = 200_000_000.0
_REBOUND_VOLUME_GATE = 1.5
_REBOUND_CLOSE_LOW_GATE = 3.0


def _screen_number(value: Any, *, positive: bool = False) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or (number <= 0 if positive else number < 0):
        return None
    return number


def _screen_empty(context: Mapping[str, Any], gaps: list[str]) -> dict:
    date = str(context.get('plan_trade_date') or '')
    day = str(context.get('market_session') or '')
    return dict(schema_version=REBOUND_SCREEN_SCHEMA, rule_version=REBOUND_SCREEN_RULE,
        target_trade_date=date, verified_session=day, status='CANNOT_CONFIRM', cards=[],
        strict=[], near=[], pending=[], gaps=sorted(set(gaps)), coverage=dict(
            input_candidate_count=0, history_complete_count=0, history_pending_count=0,
            strict_count=0, near_candidate_count=0, near_count=0, selected_count=0,
            panel_row_count=0, panel_code_count=0), input_identity=None,
        authority=None, data_context=_screen_data_context(context),
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False,
        orders_sent=False, main_screen_ready=False)


def _screen_exclusion_decision(row: Mapping[str, Any]) -> dict:
    """Explain a row omitted from strict/near without changing either gate."""
    if (row.get('history_status') != 'KNOWN'
            or type(row.get('oversold_flag')) is not bool
            or type(row.get('volume_flag_5d_ge_1_5')) is not bool):
        return dict(status='UNRESOLVED', reason_code='SCREEN_REMAINDER_GATE_STATE_UNKNOWN', reason=None)
    oversold = row['oversold_flag']
    volume = row['volume_flag_5d_ge_1_5']
    if oversold or volume:
        return dict(status='UNRESOLVED', reason_code='SCREEN_REMAINDER_GATE_STATE_INCONSISTENT', reason=None)
    close = row.get('close')
    cutoff = row.get('oversold_cutoff_80pct_prior60_high')
    volume_ratio = row.get('volume_ratio_5d')
    if not all(type(value) in (int, float) for value in (close, cutoff, volume_ratio)):
        return dict(status='UNRESOLVED', reason_code='SCREEN_REMAINDER_GATE_VALUE_MISSING', reason=None)
    reason = (
        f'收盘{close:.8g}高于60日高点80%门槛{cutoff:.8g}，超跌条件未通过；'
        f'前5日量比{volume_ratio:.8g}低于1.5，量能条件未通过；成交额与低点反弹只作观察'
    )
    return dict(status='EXCLUDED', reason_code='BOTH_REBOUND_GATES_FAILED', reason=reason)


def _screen_security_master_witness(authority_root: Path, day: str) -> tuple[dict, dict[str, Any]]:
    """Read the exact-date verified master and its immutable manifest bytes."""
    from v3_shared_data.shared_data.hk_security_master import load_verified_hk_security_master

    names, manifest = load_verified_hk_security_master(authority_root, day)
    asset_root = authority_root / 'assets' / 'hk_security_master'
    latest = json.loads((asset_root / 'latest.json').read_text(encoding='utf-8'))
    entry = latest['entries'][day]
    manifest_path = (asset_root / str(entry['manifest_relative'])).resolve()
    manifest_path.relative_to(asset_root.resolve())
    artifact_path = (asset_root / str(manifest['artifact_relative'])).resolve()
    artifact_path.relative_to(asset_root.resolve())
    manifest_bytes = manifest_path.read_bytes()
    artifact_bytes = artifact_path.read_bytes()
    return dict(
        owner='V4_SHARED_HK_SECURITY_MASTER_AUTHORITY',
        manifest_path=str(manifest_path),
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        artifact_path=str(artifact_path),
        artifact_sha256=hashlib.sha256(artifact_bytes).hexdigest(),
        row_count=manifest.get('row_count'),
        run_id=manifest.get('run_id'),
        captured_at=manifest.get('captured_at'),
        names=names,
    ), manifest


def _read_hk02_daily_supplement_witness(
    authority_root: Path, day: str, requested: list[str], cutoff: str,
    panel: Mapping[str, Any], master: Mapping[str, Any], master_names: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Read the stable exact-date HK0.2 category-4 sidecar, if published."""
    from v3_shared_data.shared_data.hk_daily_supplement import read_verified_daily_supplement

    return read_verified_daily_supplement(
        authority_root,
        target_date=day,
        requested=requested,
        research_cutoff=cutoff,
        expected_panel={
            "panel_sha256": panel.get("panel_sha256"),
            "panel_manifest_sha256": panel.get("panel_manifest_sha256"),
            "manifest_prepared_at": panel.get("panel_available_at"),
        },
        expected_master={
            "manifest_sha256": master.get("manifest_sha256"),
            "artifact_sha256": master.get("artifact_sha256"),
            "captured_at": master.get("captured_at"),
        },
        expected_codes=sorted(master_names),
    )


def rebound_v3_metrics(*, price: Any, low: Any, amount: Any, volume: Any,
                       previous5_mean: Any, prior60_high: Any) -> dict:
    """Approved V3 arithmetic, independent of phase; ``price`` is NOT ``close``.

    Decimal inequalities make the inclusive 3%/1.5 boundaries exact without a
    tolerance that could admit below-threshold values. Unknown never fills near.
    Source identity, units, session completeness and PIT are the reader's job.
    """
    from decimal import Decimal, InvalidOperation
    def number(value, positive=False):
        if value is None or isinstance(value, bool):
            return None
        try:
            out = Decimal(str(value))
            return out if out.is_finite() and (out > 0 if positive else out >= 0) else None
        except (InvalidOperation, ValueError):
            return None
    p, lo = number(price, True), number(low, True)
    a, v = number(amount), number(volume)
    mean, peak = number(previous5_mean, True), number(prior60_high, True)
    valid_price = p is not None and lo is not None and p >= lo
    gates = dict(
        amount=(Decimal(str(_REBOUND_AMOUNT_MIN)) < a <= Decimal(str(_REBOUND_AMOUNT_MAX))
                if a is not None else 'unknown'),
        oversold=(p <= Decimal('0.8') * peak if p is not None and peak is not None else 'unknown'),
        volume=(v >= Decimal(str(_REBOUND_VOLUME_GATE)) * mean
                if v is not None and mean is not None else 'unknown'),
        rebound=(p >= (Decimal('1') + Decimal(str(_REBOUND_CLOSE_LOW_GATE))/100) * lo
                 if valid_price else 'unknown'))
    strict = all(value is True for value in gates.values())
    near = (gates['amount'] is True and gates['oversold'] is True
            and all(gates[k] != 'unknown' for k in ('volume', 'rebound'))
            and sum(gates[k] is True for k in ('volume', 'rebound')) == 1)
    ratio = float(v/mean) if v is not None and mean is not None else None
    rebound = float((p/lo-1)*100) if valid_price else None
    failed = ('volume' if gates['volume'] is False else 'rebound') if near else None
    failed_value = (ratio if failed == 'volume' else rebound) if failed else None
    threshold = (_REBOUND_VOLUME_GATE if failed == 'volume' else _REBOUND_CLOSE_LOW_GATE) if failed else None
    return dict(gates=gates, strict=strict, near=near, volume_ratio_5d=ratio,
                rebound_price_vs_low_pct=rebound,
                oversold_cutoff=(float(Decimal('0.8')*peak) if peak is not None else None),
                near_failed_gate=failed, near_failed_value=failed_value,
                near_gate_value=threshold,
                near_failed_ratio=(failed_value/threshold if failed_value is not None else None))


def rebound_history_sessions(trade_date: str) -> dict:
    """Native HK securities calendar, never weekdays or last five available rows.

    Volume uses five prior FULL sessions. The approved 60-session raw high
    retains both full and half HK sessions, as the original daily panel does.
    """
    from contracts.trading_calendar import (CALENDAR_PATH, load_market_calendar,
        resolve_market_states, previous_session, TradingDayState)
    date_token(trade_date)
    calendar_bytes = CALENDAR_PATH.read_bytes()
    calendar = load_market_calendar()
    if resolve_market_states(calendar, trade_date)['hk_securities'] != TradingDayState.FULL_TRADING_DAY:
        raise ValueError('REBOUND_TARGET_NOT_FULL_HK_SESSION')
    cursor = trade_date; dates60 = []; dates5 = []
    while len(dates60) < 60 or len(dates5) < 5:
        cursor = previous_session(calendar, cursor, market='hk_securities')
        state = resolve_market_states(calendar, cursor)['hk_securities']
        if len(dates60) < 60: dates60.append(cursor)
        if state == TradingDayState.FULL_TRADING_DAY and len(dates5) < 5: dates5.append(cursor)
    if CALENDAR_PATH.read_bytes() != calendar_bytes:
        raise ValueError('REBOUND_CALENDAR_CHANGED_DURING_READ')
    return dict(previous5=sorted(dates5), prior60=sorted(dates60), panel_session=dates60[0],
                calendar_sha256=hashlib.sha256(calendar_bytes).hexdigest())


def rebound_history_rows(frame: Any, symbols: list[str], sessions: Mapping[str, Any]) -> dict:
    """Pure original-panel projection. Missing/duplicate dates are not substituted."""
    required={'trade_date_compact','code_norm','high','trade'}
    if not required.issubset(set(frame.columns)): raise ValueError('REBOUND_PANEL_COLUMNS_MISSING')
    data=frame.copy()
    data['trade_date_compact']=data['trade_date_compact'].astype(str)
    data['code_norm']=data['code_norm'].astype(str)
    result={}
    for symbol in sorted(set(symbols)):
        rows=data.loc[(data['code_norm']==symbol) & data['trade_date_compact'].isin(sessions['prior60'])]
        duplicate=rows['trade_date_compact'].duplicated().any()
        day_rows={str(r['trade_date_compact']): r for _,r in rows.iterrows()} if not duplicate else {}
        hi=[_screen_number(day_rows.get(d,{}).get('high'),positive=True) for d in sessions['prior60']]
        vol=[_screen_number(day_rows.get(d,{}).get('trade')) for d in sessions['previous5']]
        gaps=[]
        if duplicate:gaps.append('REBOUND_DUPLICATE_HISTORY_SESSION')
        if len(hi)!=60 or any(v is None for v in hi):gaps.append('REBOUND_PRIOR60_HIGH_INCOMPLETE')
        if len(vol)!=5 or any(v is None for v in vol):gaps.append('REBOUND_PREVIOUS5_VOLUME_INCOMPLETE')
        mean=sum(vol)/5 if len(vol)==5 and all(v is not None for v in vol) else None
        if mean==0:gaps.append('REBOUND_PREVIOUS5_MEAN_ZERO')
        result[symbol]=dict(prior60_high=max(hi) if len(hi)==60 and all(v is not None for v in hi) else None,
            previous5_mean=mean, previous5_count=sum(v is not None for v in vol),
            prior60_count=sum(v is not None for v in hi), gaps=gaps)
    return result


def rebound_native_evidence(manifest: Mapping[str, Any], *, required_session: str,
                            observed_at: datetime, master_captured_at: str | None = None) -> dict:
    """Interpret ORIGINAL-owner metadata without promoting a bare unit string.

    v1 records byte layout, source hashes and read times ONLY. Its explicit
    unknowns are not vendor attestations, and its increment scope cannot certify
    all inherited history. No conversion to shares/HKD is licensed by v1.
    """
    from datetime import timezone
    if observed_at.tzinfo is None:
        raise ValueError('REBOUND_NATIVE_OBSERVATION_CLOCK_NAIVE')
    observed = observed_at.astimezone(timezone.utc)
    if manifest.get('panel_max_date') != required_session:
        raise ValueError('REBOUND_NATIVE_PANEL_SESSION_MISMATCH')
    native = manifest.get('native_observation')
    gaps = ['REBOUND_HISTORY_VOLUME_UNIT_NOT_PROVEN', 'REBOUND_HISTORY_PRICE_CURRENCY_NOT_PROVEN']
    if any(manifest.get(k) is not None for k in ('volume_unit','currency','price_currency','amount_unit')):
        gaps.append('REBOUND_BARE_UNIT_DECLARATION_NOT_ATTESTED')
    dates = dict(data_session=required_session, reader_observed_at=observed.isoformat(),
                 manifest_available_at=None, manifest_prepared_at=None,
                 observation_status='LEGACY_NO_NATIVE_OBSERVATION',
                 provider_session_finality='NOT_ATTESTED_BY_PROVIDER',
                 master_captured_at=master_captured_at)
    if master_captured_at is not None:
        master_time = timestamp(master_captured_at)
        if master_time is None or master_time > observed:
            raise ValueError('REBOUND_NATIVE_MASTER_AFTER_READ')
    if native is not None:
        fail = lambda: ValueError('REBOUND_NATIVE_OBSERVATION_CONTRACT_INVALID')
        if not isinstance(native, Mapping): raise fail()
        if (native.get('schema_version') != 'v3_shared_data.hk02_native_observation.v1'
            or native.get('scope') != 'NEW_INCREMENT_ONLY'
            or native.get('requested_through_date') != required_session
            or native.get('session_finality') != 'NOT_ATTESTED_BY_PROVIDER'
            or not re.fullmatch(r'[0-9a-f]{64}', str(native.get('owner_source_sha256') or ''))):
            raise fail()
        started, completed = timestamp(native.get('read_started_at')), timestamp(native.get('read_completed_at'))
        prepared = timestamp(manifest.get('manifest_prepared_at'))
        if (started is None or completed is None or prepared is None
            or not started <= completed <= prepared <= observed):
            raise ValueError('REBOUND_NATIVE_OBSERVATION_TIME_INVALID')
        expected_fields = {
            'trade': dict(native_field='trade_v',byte_offset=24,storage_type='uint32_le',
                          scale_applied=1,unit=None,unit_status='NOT_PROVEN'),
            'amount': dict(native_field='amount_v',byte_offset=20,storage_type='float32_le',
                           scale_applied=1,unit=None,currency=None,unit_status='NOT_PROVEN'),
            'price': dict(native_fields=['open_v','high_v','low_v','close_v'],byte_offsets=[4,8,12,16],
                          storage_type='float32_le',scale_applied=1,currency=None,
                          currency_status='NOT_PROVEN',transform='NONE')}
        # JSON equality is type-sensitive (True must not impersonate 1).
        if json.dumps(native.get('fields'),sort_keys=True,allow_nan=False) != json.dumps(expected_fields,sort_keys=True):
            raise fail()
        sources = native.get('source_files')
        selected = native.get('selected_dates')
        after = native.get('requested_after_date')
        if (not isinstance(sources,list) or not sources or not isinstance(selected,list)
            or selected != sorted(set(selected)) or not re.fullmatch(r'\d{8}',str(after or ''))
            or not selected or not all(isinstance(d,str) and re.fullmatch(r'\d{8}',d)
                                      and after < d <= required_session for d in selected)
            or selected != manifest.get('new_dates')): raise fail()
        names = set(); row_count = 0
        for source in sources:
            if not isinstance(source,Mapping): raise fail()
            name = str(source.get('source_relative') or '')
            size, count = source.get('size_bytes'), source.get('selected_rows')
            if (not re.fullmatch(r'vipdoc/ds/lday/71#\d{5}\.day',name) or name in names
                or not re.fullmatch(r'[0-9a-f]{64}',str(source.get('sha256') or ''))
                or type(size) is not int or size <= 0 or size % 32
                or type(count) is not int or not 0 < count <= size//32): raise fail()
            names.add(name);row_count+=count
        # The original updater deduplicates selected date/code rows; this is a
        # bound, NOT a claim that the raw selection and final row count are equal.
        count = manifest.get('new_row_count')
        if type(count) is not int or not 0 < count <= row_count: raise fail()
        dates.update(observation_status='NATIVE_SOURCE_READ_RECORDED',
                     read_started_at=started.isoformat(),read_completed_at=completed.isoformat(),
                     manifest_prepared_at=prepared.isoformat())
    else:
        gaps.append('REBOUND_NATIVE_PUBLISHER_OBSERVATION_MISSING')
    return dict(volume_unit=None,price_currency=None,price_basis='RAW',
                native_observation=native,date_evidence=dates,
                unit_evidence=dict(status='NOT_PROVEN',scope='ENTIRE_SELECTED_HISTORY',
                    conversion_applied=False,legacy_declared_volume_unit=manifest.get('volume_unit'),
                    source_finality='NOT_ATTESTED_BY_PROVIDER'),gaps=sorted(set(gaps)))


def read_rebound_history(authority_root: Path | None, trade_date: str, symbols: list[str],
                         *, now: datetime | None = None) -> dict:
    """Read the same HK02/master authorities, never a current-day close row.

    The caller is the original 1530 materializer. It records actual read
    completion before requesting the original quote; an old manifest date is
    NOT invented as historical availability. This function writes nothing.
    """
    result=dict(rule_version=REBOUND_SCREEN_RULE,trade_date=trade_date,status='CANNOT_CONFIRM',
                sessions=None,symbols={},source_files=[],gaps=[],volume_unit=None,
                price_currency=None,price_basis=None)
    if authority_root is None:
        result['gaps']=['REBOUND_SHARED_AUTHORITY_ROOT_NOT_BOUND'];return result
    try:
        from infrastructure.manager_input_attestation import resolve as owned_resolve
        root=Path(authority_root).expanduser().resolve()
        sessions=rebound_history_sessions(trade_date);result['sessions']=sessions
        panel,gaps=_read_hk02_panel_witness(root,sessions['panel_session'])
        if panel is None:
            result['gaps']=['REBOUND_PRIOR_PANEL_UNVERIFIED',*gaps];return result
        from v3_shared_data.shared_data.store import StoreError
        try:
            master,manifest=_screen_security_master_witness(root,trade_date)
        except StoreError:
            # Actual owner rejects an absent/invalid exact-date master. This is
            # an input gap, not a reason to substitute a later or latest master.
            result['gaps']=['REBOUND_EXACT_SECURITY_MASTER_UNVERIFIED']
            return result
        captured=timestamp(master.get('captured_at'))
        clock=now or datetime.now(HK)
        if clock.tzinfo is None or captured is None or captured>clock:
            raise ValueError('REBOUND_MASTER_TIME_UNVERIFIED')
        # Native readers established authority; also bind every immutable byte
        # and disallow symlink path components for this consumer's replays.
        refs=[]
        for owner,fields in [(panel['owner'], [('panel_manifest_path','panel_manifest_sha256'),('panel_path','panel_sha256')]),
                             (master['owner'], [('manifest_path','manifest_sha256'),('artifact_path','artifact_sha256')])]:
            source=panel if owner==panel['owner'] else master
            for pathkey,shakey in fields:
                ref=Path(source[pathkey]).relative_to(root).as_posix()
                path=owned_resolve(root,ref);raw=path.read_bytes()
                if hashlib.sha256(raw).hexdigest()!=source[shakey]:raise ValueError('REBOUND_SOURCE_CHANGED_DURING_READ')
                refs.append(dict(owner=owner,artifact_ref=ref,sha256=source[shakey]))
        import pandas as pd
        frame=pd.read_parquet(panel['panel_path'],columns=['trade_date_compact','code_norm','high','trade'])
        if str(frame['trade_date_compact'].astype(str).max())!=sessions['panel_session']:
            raise ValueError('REBOUND_PANEL_DATE_CONTENT_MISMATCH')
        result['symbols']=rebound_history_rows(frame,symbols,sessions)
        for symbol,row in result['symbols'].items():
            if symbol not in master['names']:row['gaps'].append('REBOUND_EXACT_SECURITY_MASTER_MISSING')
        # Cross-owner volume unit is never inferred from turnover, price,
        # lot_size, a provider volume_ratio, a stock name or a synthetic fixture.
        panel_manifest=json.loads(Path(panel['panel_manifest_path']).read_bytes())
        audit = rebound_native_evidence(panel_manifest, required_session=sessions['panel_session'],
            observed_at=clock, master_captured_at=master.get('captured_at'))
        result.update(source_files=refs, **audit)
        result['status']='PARTIAL' if result['gaps'] or any(r['gaps'] for r in result['symbols'].values()) else 'READY'
        for ref in refs:
            if hashlib.sha256(owned_resolve(root,ref['artifact_ref']).read_bytes()).hexdigest()!=ref['sha256']:
                raise ValueError('REBOUND_SOURCE_CHANGED_DURING_READ')
        return result
    except (ImportError,OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        # Exception text may contain host paths; only bounded type/code leaves.
        code=str(exc) if isinstance(exc,ValueError) and re.fullmatch(r'REBOUND_[A-Z0-9_]+',str(exc)) else type(exc).__name__
        result.update(status='CANNOT_CONFIRM',symbols={},source_files=[],gaps=['REBOUND_HISTORY_READ_FAILED:'+code])
        return result


def _screen_panel_volume_evidence(panel: Mapping[str, Any], context: Mapping[str, Any],
                                  required_sessions: list[str]) -> dict:
    """Read original volume provenance without inventing an owner attestation.

    The current HK02 native observation v1 proves byte fields and increment
    read times. It explicitly does not attest units or inherited-history scale.
    A bare SHARES/LOTS string or security-master lot size cannot upgrade it.
    """
    result = dict(status='NOT_PROVEN', unit_status='NOT_PROVEN', unit=None,
        scale_applied=None, source=panel['owner'], native_field='trade',
        required_sessions=list(required_sessions), scope='ALL_SIX_REQUIRED_SESSIONS',
        source_sha256=panel['panel_sha256'], manifest_sha256=panel['panel_manifest_sha256'],
        same_source_status='PANEL_ONLY_INHERITED_HISTORY_SCALE_NOT_ATTESTED',
        gaps=['SCREEN_VOLUME_UNIT_OR_SCALE_NOT_PROVEN'])
    try:
        from infrastructure.owned_io import SafeRoot
        manifest_path = Path(panel['panel_manifest_path'])
        raw = SafeRoot(manifest_path.parent).read_bytes(manifest_path.name, max_bytes=1024*1024)
        if hashlib.sha256(raw).hexdigest() != panel['panel_manifest_sha256']:
            raise ValueError('SCREEN_VOLUME_MANIFEST_CHANGED_DURING_READ')
        manifest = json.loads(raw)
        audit = rebound_native_evidence(manifest,
            required_session=str(context['market_session']),
            observed_at=timestamp(context['research_cutoff']))
        result['owner_unit_evidence'] = audit['unit_evidence']
        result['native_observation_status'] = audit['date_evidence']['observation_status']
        result['gaps'].extend(gap for gap in audit['gaps']
                             if gap != 'REBOUND_HISTORY_PRICE_CURRENCY_NOT_PROVEN')
        if audit['date_evidence']['observation_status'] == 'NATIVE_SOURCE_READ_RECORDED':
            native = audit['native_observation']
            result['native_scale_applied'] = native['fields']['trade']['scale_applied']
            result['scale_scope'] = native['scope']
            result['native_selected_dates'] = list(native['selected_dates'])
        # The existing owner reader deliberately returns NOT_PROVEN. Future
        # owner attestations need an explicit reader-contract change; arbitrary
        # extra manifest keys are never treated as a verified source contract.
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        code = str(exc)
        if not re.fullmatch(r'(?:SCREEN|REBOUND)_[A-Z0-9_]+', code):
            code = type(exc).__name__
        result['gaps'].append('SCREEN_VOLUME_NATIVE_EVIDENCE_UNVERIFIED:' + code)
    result['gaps'] = sorted(set(result['gaps']))
    return result


def _screen_supplement_volume_evidence(supplement: Mapping[str, Any],
                                       required_sessions: list[str]) -> dict:
    """The native six-bar reader verifies identity, while units stay unknown."""
    return dict(status='NOT_PROVEN', unit_status='NOT_PROVEN', unit=None,
        scale_applied=1, source='PYTDX_EXHQ_CATEGORY_4_MARKET_71', native_field='trade',
        required_sessions=list(required_sessions), scope='ALL_SIX_REQUIRED_SESSIONS',
        source_sha256=supplement['raw_capture_sha256'],
        manifest_sha256=supplement['manifest_sha256'],
        same_source_status='SIX_NATIVE_BARS_SAME_SOURCE_UNIT_NOT_ATTESTED',
        gaps=['SCREEN_VOLUME_UNIT_OR_SCALE_NOT_PROVEN'])


def read_rebound_screen(authority_root: Path | None, context: Mapping[str, Any]) -> dict:
    """Recompute the bounded REBOUND_V3 screen from the existing HK panel.

    The panel, its manifest and the date-specific security master are only
    read.  No task output, static longlist, symbol list or new market producer
    participates in this calculation. Every row from the supplied completed
    session is evaluated; only the 80%-of-prior-60-high and previous-five-day
    volume-ratio conditions decide strict/near qualification. Fully known rows
    failing both existing gates are also returned as exclusions with their
    exact gate values. Amount and close-to-low rebound remain observations.
    """
    if ('market_session' in context
            and not re.fullmatch(r'\d{8}', str(context.get('market_session') or ''))):
        return _screen_empty(context, ['SCREEN_MARKET_SESSION_UNVERIFIED'])
    try:
        context = screen_context(context)
    except (ImportError, OSError, ValueError, KeyError, TypeError) as exc:
        code = str(exc)
        if not re.fullmatch(r'(?:SCREEN|WORKSPACE)_[A-Z0-9_]+', code):
            code = type(exc).__name__
        return _screen_empty(context, ['SCREEN_SESSION_CONTEXT_UNVERIFIED:' + code])
    day = str(context.get('market_session') or '')
    if not re.fullmatch(r'\d{8}', day):
        return _screen_empty(context, ['SCREEN_MARKET_SESSION_UNVERIFIED'])
    if authority_root is None:
        return _screen_empty(context, ['SCREEN_AUTHORITY_ROOT_NOT_BOUND'])
    try:
        root = Path(authority_root).expanduser().resolve()
        try:
            history_sessions = rebound_history_sessions(day)
            prior60_session_dates = list(history_sessions.get('prior60') or [])
            previous5_session_dates = list(history_sessions.get('previous5') or [])
            if (len(prior60_session_dates) != 60 or len(set(prior60_session_dates)) != 60
                    or any(not re.fullmatch(r'\d{8}', str(value)) for value in prior60_session_dates)
                    or len(previous5_session_dates) != 5 or len(set(previous5_session_dates)) != 5
                    or any(not re.fullmatch(r'\d{8}', str(value)) for value in previous5_session_dates)
                    or not set(previous5_session_dates).issubset(prior60_session_dates)):
                return _screen_empty(context, ['SCREEN_HISTORY_CALENDAR_SESSIONS_INVALID'])
        except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            return _screen_empty(context, ['SCREEN_HISTORY_CALENDAR_UNVERIFIED:' + type(exc).__name__])
        panel, panel_gaps = _read_hk02_panel_witness(
            root, day, research_cutoff=context.get('research_cutoff'),
            required_history_date=previous5_session_dates[-1])
        if panel is None:
            return _screen_empty(context, ['SCREEN_PANEL_AUTHORITY_UNVERIFIED', *panel_gaps])
        try:
            from v3_shared_data.shared_data.store import StoreError
        except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            return _screen_empty(context, ['SCREEN_SECURITY_MASTER_READ_FAILED:' + type(exc).__name__])
        try:
            master, master_manifest = _screen_security_master_witness(root, day)
        except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError, StoreError) as exc:
            return _screen_empty(context, ['SCREEN_SECURITY_MASTER_READ_FAILED:' + type(exc).__name__])
        master_captured_at = timestamp(master.get('captured_at'))
        if master_captured_at is None or master_captured_at > timestamp(context['research_cutoff']):
            return _screen_empty(context, ['SCREEN_SECURITY_MASTER_AFTER_CUTOFF_OR_UNVERIFIED'])
        required_volume_sessions = [*previous5_session_dates, day]
        panel_volume_evidence = _screen_panel_volume_evidence(panel, context, required_volume_sessions)
        master_names = master.get('names') or {}
        try:
            import pandas as pd
            frame = pd.read_parquet(panel['panel_path'], columns=[
                'trade_date_compact', 'code_norm', 'name', 'open', 'high', 'low',
                'close', 'amount', 'trade', 'pre_close',
            ])
        except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            return _screen_empty(context, ['SCREEN_PANEL_READ_FAILED:' + type(exc).__name__])
        required = {'trade_date_compact', 'code_norm', 'high', 'low', 'close', 'amount', 'trade', 'pre_close'}
        if not required.issubset(set(frame.columns)):
            return _screen_empty(context, ['SCREEN_PANEL_SCHEMA_INVALID'])
        frame = frame.copy()
        frame['trade_date_compact'] = frame['trade_date_compact'].astype(str).str.zfill(8)
        frame['code_norm'] = frame['code_norm'].astype(str).str.upper()
        target = frame.loc[frame['trade_date_compact'] == day].copy()
        if target.empty:
            return _screen_empty(context, ['SCREEN_PANEL_TARGET_SESSION_EMPTY'])
        if target['code_norm'].duplicated().any():
            return _screen_empty(context, ['SCREEN_PANEL_TARGET_DUPLICATE_CODE'])
        codes = set(target['code_norm'].tolist())
        target_by_code = {
            str(row['code_norm']): row.to_dict()
            for _, row in target.iterrows()
        }
        history = frame.loc[
            frame['code_norm'].isin(codes) & (frame['trade_date_compact'] < day)
        ].copy().sort_values(['code_norm', 'trade_date_compact'])
        # Keep the established canonical panel volume path whenever that
        # code has a complete 60-session high series, five valid prior-session
        # volumes, and a complete target bar. A sidecar is consulted only for
        # codes with a real gap; if selected for a code, all six volume bars
        # must come from that same source.
        canonical_complete_codes: set[str] = set()
        for code in codes:
            code_history = history.loc[history['code_norm'].eq(code)]
            prior_rows = code_history.loc[
                code_history['trade_date_compact'].isin(prior60_session_dates)
            ]
            previous_rows = code_history.loc[
                code_history['trade_date_compact'].isin(previous5_session_dates)
            ]
            current = target_by_code.get(code)
            prior_dates = prior_rows['trade_date_compact'].tolist()
            previous_dates = previous_rows['trade_date_compact'].tolist()
            complete_prior = (
                len(prior_rows) == 60 and len(set(prior_dates)) == 60
                and set(prior_dates) == set(prior60_session_dates)
                and all(_screen_number(value, positive=True) is not None
                        for value in prior_rows['high'].tolist())
            )
            panel_volumes = [_screen_number(value)
                             for value in previous_rows['trade'].tolist()]
            complete_previous = (
                len(previous_rows) == 5 and len(set(previous_dates)) == 5
                and set(previous_dates) == set(previous5_session_dates)
                and all(value is not None for value in panel_volumes)
                and sum(panel_volumes) > 0
            )
            complete_target = bool(current) and all(
                _screen_number(current.get(field), positive=True) is not None
                for field in ('open', 'high', 'low', 'close')
            ) and _screen_number(current.get('trade')) is not None
            if complete_prior and complete_previous and complete_target:
                canonical_complete_codes.add(code)

        supplement = None
        supplement_gaps: list[str] = []
        supplement_attempted = False
        codes_needing_repair = codes - canonical_complete_codes
        if codes_needing_repair and context.get('research_cutoff'):
            supplement_attempted = True
            try:
                supplement = _read_hk02_daily_supplement_witness(
                    root, day, [*previous5_session_dates, day],
                    str(context['research_cutoff']), panel, master, master_names,
                )
                if supplement is None:
                    supplement_gaps.append('SCREEN_DAILY_SUPPLEMENT_NOT_AVAILABLE')
            except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                code = str(exc) if isinstance(exc, ValueError) and re.fullmatch(
                    r'SCREEN_DAILY_SUPPLEMENT_[A-Z0-9_]+|HK_DAILY_SUPPLEMENT_[A-Z0-9_]+', str(exc)
                ) else type(exc).__name__
                supplement_gaps.append('SCREEN_DAILY_SUPPLEMENT_UNVERIFIED:' + code)
                supplement = None
        supplement_records = (supplement or {}).get('records') or {}
        supplement_volume_evidence = (_screen_supplement_volume_evidence(supplement, required_volume_sessions)
                                      if supplement is not None else None)
        supplement_bars: dict[str, dict[str, Any]] = {}
        supplement_volume_codes: set[str] = set()
        for code, record in supplement_records.items():
            if record.get('status') in {'INVALID', 'QUERY_FAILED'}:
                continue
            supplement_bars[code] = {
                str(bar.get('trade_date')): bar for bar in (record.get('bars') or [])
            }
            requested_volume_dates = [*previous5_session_dates, day]
            if (record.get('status') == 'READY'
                    and all(session in supplement_bars[code] for session in requested_volume_dates)
                    and all(_screen_number(supplement_bars[code][session].get('trade')) is not None
                            for session in requested_volume_dates)):
                supplement_volume_codes.add(code)
        # Category-4 bars supply the same-source native trade values for the
        # target and previous five sessions. Their OHLC may fill only missing
        # panel cells in those six sessions; existing panel values stay intact.
        price_overlay_codes: set[str] = set()
        if supplement is not None:
            add_history: list[dict[str, Any]] = []
            for code in sorted(codes):
                for session in previous5_session_dates:
                    bar = supplement_bars.get(code, {}).get(session)
                    if bar is None:
                        continue
                    matching = history.index[
                        history['code_norm'].eq(code)
                        & history['trade_date_compact'].eq(session)
                    ].tolist()
                    if len(matching) > 1:
                        continue
                    if not matching:
                        price_overlay_codes.add(code)
                        add_history.append({
                            'trade_date_compact': session, 'code_norm': code,
                            'name': (master_names.get(code) or {}).get('name') or code,
                            'open': bar.get('open'), 'high': bar.get('high'),
                            'low': bar.get('low'), 'close': bar.get('close'),
                            'amount': None, 'trade': None, 'pre_close': None,
                        })
                    else:
                        index = matching[0]
                        for field in ('open', 'high', 'low', 'close'):
                            if pd.isna(history.at[index, field]):
                                history.at[index, field] = bar.get(field)
                                price_overlay_codes.add(code)
            if add_history:
                history = pd.concat([history, pd.DataFrame(add_history)], ignore_index=True)
                history = history.sort_values(['code_norm', 'trade_date_compact'])
        history_positions_by_code = history.groupby('code_norm', sort=False).indices
        master_names = master.get('names') or {}
        gaps = list(panel_gaps)
        rows: list[dict[str, Any]] = []
        sidecar_refs = []
        if supplement is not None:
            pointer = supplement['pointer']
            sidecar_refs = [
                dict(owner='V4_SHARED_HK_0_2_DAILY_SUPPLEMENT',
                     artifact_path=str(root / 'assets' / 'hk_0_2' / pointer['raw_capture_relative']),
                     artifact_sha256=supplement['raw_capture_sha256'],
                     manifest_path=str(root / 'assets' / 'hk_0_2' / pointer['manifest_relative']),
                     manifest_sha256=supplement['manifest_sha256'],
                     pointer_path=str(root / 'assets' / 'hk_0_2' / 'daily_supplements' / 'pointers' / f'{day}.json'),
                     pointer_sha256=hashlib.sha256(json.dumps(pointer, ensure_ascii=False,
                         sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest())
            ]
        for code in sorted(codes):
            current = target_by_code.get(code, {})
            supplement_record = supplement_records.get(code)
            target_bar = supplement_bars.get(code, {}).get(day)
            use_supplement_volume = (
                code not in canonical_complete_codes and code in supplement_volume_codes
            )
            volume_evidence = (supplement_volume_evidence if use_supplement_volume
                               else panel_volume_evidence)
            volume_proven = volume_evidence['status'] == 'OWNER_VERIFIED'
            if not current:
                current = {
                    'code_norm': code, 'name': (master_names.get(code) or {}).get('name') or code,
                    'open': None, 'high': None, 'low': None, 'close': None,
                    'amount': None, 'trade': None, 'pre_close': None,
                }
            if target_bar is not None:
                for field in ('open', 'high', 'low', 'close'):
                    value = current.get(field)
                    if value is None or pd.isna(value):
                        current[field] = target_bar.get(field)
                        price_overlay_codes.add(code)
            # The sidecar ratio uses all six native category-4 bars. When that
            # set is unavailable, panel trade remains panel-only and is never
            # mixed with sidecar trade. Amount is never inferred from sidecar.
            current_volume_raw = (
                target_bar.get('trade') if use_supplement_volume else current.get('trade')
            )
            positions = history_positions_by_code.get(code)
            code_history = history.iloc[positions] if positions is not None else history.iloc[0:0]
            duplicate_mask = code_history['trade_date_compact'].duplicated(keep=False)
            duplicate_history_dates = set(code_history.loc[duplicate_mask, 'trade_date_compact'].tolist())
            if duplicate_history_dates:
                gaps.append('SCREEN_HISTORY_DUPLICATE_DATE:' + code)
            duplicate_prior60_dates = duplicate_history_dates.intersection(prior60_session_dates)
            duplicate_previous5_dates = duplicate_history_dates.intersection(previous5_session_dates)
            prior60 = code_history.loc[code_history['trade_date_compact'].isin(prior60_session_dates)]
            previous5 = code_history.loc[code_history['trade_date_compact'].isin(previous5_session_dates)]
            previous20 = code_history.tail(20)
            count60 = int(len(prior60))
            valid_highs = prior60['high'].map(lambda value: _screen_number(value, positive=True)).dropna()
            if use_supplement_volume:
                volume_bars = [supplement_bars.get(code, {}).get(session)
                               for session in previous5_session_dates]
                valid_vol5 = [(_screen_number(bar.get('trade')) if bar is not None else None)
                              for bar in volume_bars]
            else:
                valid_vol5 = [_screen_number(value) for value in previous5['trade'].tolist()]
            valid_previous5_count = sum(value is not None for value in valid_vol5)
            valid_vol20 = previous20['trade'].map(lambda value: _screen_number(value)).dropna()
            available_history_dates = set(code_history['trade_date_compact'].tolist())
            missing_prior60_dates = [session for session in prior60_session_dates
                                     if session not in available_history_dates]
            missing_previous5_dates = [session for session in previous5_session_dates
                                       if session not in available_history_dates]
            prior60_high = (float(valid_highs.max())
                            if count60 == 60 and len(valid_highs) == 60
                            and not missing_prior60_dates and not duplicate_prior60_dates else None)
            previous5_mean = (float(sum(valid_vol5) / 5)
                              if len(previous5) == 5 and len(valid_vol5) == 5
                              and all(value is not None for value in valid_vol5)
                              and not missing_previous5_dates and not duplicate_previous5_dates else None)
            previous20_mean = float(valid_vol20.mean()) if len(previous20) == 20 and len(valid_vol20) == 20 else None
            close = _screen_number(current.get('close'), positive=True)
            low = _screen_number(current.get('low'), positive=True)
            high = _screen_number(current.get('high'), positive=True)
            amount = _screen_number(current.get('amount'))
            current_volume = _screen_number(current_volume_raw)
            previous_close = _screen_number(current.get('pre_close'), positive=True)
            rebound = ((close / low) - 1.0) * 100.0 if close is not None and low is not None else None
            volume_ratio = (current_volume / previous5_mean
                            if current_volume is not None and previous5_mean not in (None, 0) else None)
            volume_ratio20 = (current_volume / previous20_mean
                              if not use_supplement_volume and current_volume is not None
                              and previous20_mean not in (None, 0) else None)
            close_position = ((close - low) / (high - low)
                              if close is not None and low is not None and high is not None and high > low else None)
            oversold = (bool(close <= _REBOUND_OVERSOLD_RATIO * prior60_high)
                        if prior60_high is not None and close is not None else None)
            if (volume_proven and current_volume is not None and previous5_mean not in (None, 0)
                    and len(valid_vol5) == 5 and all(value is not None for value in valid_vol5)):
                from decimal import Decimal
                volume_flag = bool(
                    Decimal(str(current_volume)) * Decimal('5')
                    >= Decimal(str(_REBOUND_VOLUME_GATE))
                    * sum((Decimal(str(value)) for value in valid_vol5), Decimal('0'))
                )
            else:
                volume_flag = None
            # Retained as display context only. It is not an admission gate.
            rebound_flag = (bool(rebound >= _REBOUND_CLOSE_LOW_GATE)
                            if rebound is not None else None)
            complete_prior60 = (not missing_prior60_dates and not duplicate_prior60_dates
                                and count60 == 60 and len(valid_highs) == 60)
            complete_previous5 = (not missing_previous5_dates and len(previous5) == 5
                                  and not duplicate_previous5_dates and len(valid_vol5) == 5
                                  and previous5_mean not in (None, 0))
            unknown_reasons = []
            if not volume_proven:
                unknown_reasons.append('VOLUME_UNIT_OR_SCALE_NOT_PROVEN')
                gaps.extend(volume_evidence['gaps'])
            if count60 < 60:
                unknown_reasons.append(f'PRIOR_60_SESSIONS_INCOMPLETE:{count60}')
            if missing_prior60_dates:
                unknown_reasons.append(f'PRIOR_60_SESSION_DATES_MISSING:{len(missing_prior60_dates)}')
            if duplicate_prior60_dates:
                unknown_reasons.append(f'PRIOR_60_SESSION_DATES_DUPLICATE:{len(duplicate_prior60_dates)}')
            if len(valid_highs) < 60:
                unknown_reasons.append(f'PRIOR_60_VALID_HIGHS_INCOMPLETE:{len(valid_highs)}')
            if len(previous5) < 5:
                unknown_reasons.append(f'PREVIOUS_5_SESSIONS_INCOMPLETE:{len(previous5)}')
            if missing_previous5_dates:
                unknown_reasons.append(f'PREVIOUS_5_FULL_SESSION_DATES_MISSING:{len(missing_previous5_dates)}')
            if duplicate_previous5_dates:
                unknown_reasons.append(f'PREVIOUS_5_FULL_SESSION_DATES_DUPLICATE:{len(duplicate_previous5_dates)}')
            elif len(valid_vol5) < 5:
                unknown_reasons.append(f'PREVIOUS_5_VALID_VOLUMES_INCOMPLETE:{len(valid_vol5)}')
            if previous5_mean == 0:
                unknown_reasons.append('PREVIOUS_5_MEAN_VOLUME_ZERO')
            if close is None:
                unknown_reasons.append('CURRENT_CLOSE_MISSING_OR_INVALID')
            if current_volume is None:
                unknown_reasons.append('CURRENT_VOLUME_MISSING_OR_INVALID')
            if supplement_attempted and supplement is None and code not in canonical_complete_codes:
                unknown_reasons.append('DAILY_SUPPLEMENT_NOT_AVAILABLE_OR_UNVERIFIED')
            elif (supplement_attempted and supplement is not None
                  and supplement_record is None and code not in canonical_complete_codes):
                unknown_reasons.append('DAILY_SUPPLEMENT_CODE_RECORD_MISSING')
            elif (supplement_attempted and supplement_record is not None
                  and target_bar is None and code not in canonical_complete_codes
                  and not use_supplement_volume):
                unknown_reasons.append('DAILY_SUPPLEMENT_TARGET_BAR_MISSING')
            if supplement_record is not None and supplement_record.get('status') in {'INVALID', 'QUERY_FAILED'}:
                unknown_reasons.append('DAILY_SUPPLEMENT_CODE_' + str(supplement_record.get('status')))
            numeric_history_complete = (complete_prior60 and complete_previous5 and close is not None
                                        and current_volume is not None)
            history_status = ('KNOWN' if numeric_history_complete and volume_proven else 'PARTIAL_UNKNOWN')
            strict = bool(history_status == 'KNOWN' and oversold is True and volume_flag is True)
            known_gate_count = int(oversold is not None) + int(volume_flag is not None)
            passing_gate_count = int(oversold is True) + int(volume_flag is True)
            near_eligible = bool(history_status == 'KNOWN' and known_gate_count == 2 and passing_gate_count == 1)
            failed_gate = None
            failed_value = None
            gate_value = None
            gate_gap_ratio = None
            gate_gap_value = None
            if near_eligible:
                if volume_flag is False:
                    failed_gate, failed_value, gate_value = 'volume_5d_ratio', volume_ratio, _REBOUND_VOLUME_GATE
                else:
                    failed_gate = 'oversold_close_le_80pct_prior60_high'
                    failed_value = close
                    gate_value = _REBOUND_OVERSOLD_RATIO * prior60_high
                gate_gap_value = (abs(failed_value - gate_value)
                                  if failed_value is not None and gate_value is not None else None)
                gate_gap_ratio = (gate_gap_value / abs(gate_value)
                                  if gate_gap_value is not None and gate_value not in (None, 0) else None)
            name = str(master_names.get(code, {}).get('name') or current.get('name') or code).strip() or code
            if code not in master_names:
                gaps.append('SCREEN_SECURITY_MASTER_NAME_MISSING:' + code)
            row = dict(
                classification=None, qualification_status='RESEARCH_ONLY_CANDIDATE', code=code, name=name,
                verified_session=int(day), target_monday=int(context.get('plan_trade_date') or 0),
                amount_hkd=amount,
                connect_eligibility='TARGET_DATE_AUTHORITY_NOT_EVALUATED',
                membership_source=dict(owner=panel['owner'], source_date=day,
                                       payload_sha256=panel['panel_sha256'], exchange='HK_CONNECT'),
                close=close, prev_close=previous_close,
                day_positive_close_gt_prev_close=(bool(close > previous_close) if close is not None and previous_close is not None else None),
                pct_change=(((close / previous_close) - 1.0) * 100.0
                            if close is not None and previous_close not in (None, 0) else None),
                current_volume=current_volume, update_time=None, close_position_0_low_1_high=close_position,
                rebound_close_vs_low_pct=rebound, rebound_ge_3pct=(rebound_flag if rebound is not None else None),
                recent_3_session_return_pct=None, recent_5_session_return_pct=None,
                history_status=history_status, history_unknown_reasons=(';'.join(unknown_reasons) or None),
                history_numeric_status='KNOWN' if numeric_history_complete else 'PARTIAL_UNKNOWN',
                history_raw_status=(str(supplement_record.get('status'))
                                    if supplement_record is not None else 'DAILY_SUPPLEMENT_NOT_AVAILABLE'),
                history_raw_error=(supplement_record.get('error_code')
                                   if supplement_record is not None else None),
                prior60_session_count=count60, previous5_session_count=valid_previous5_count,
                previous20_session_count=int(len(previous20)), prior60_session_high=prior60_high,
                oversold_cutoff_80pct_prior60_high=(0.8 * prior60_high if prior60_high is not None else None),
                previous5_mean_volume=previous5_mean, volume_ratio_5d=volume_ratio,
                volume_ratio_status='OWNER_VERIFIED' if volume_proven else 'UNVERIFIED_UNIT_OR_SCALE',
                volume_ratio_current_to_previous5_mean=volume_ratio,
                previous20_mean_volume_background=previous20_mean,
                volume_ratio_20d_background=volume_ratio20,
                volume_ratio_current_to_previous20_mean_background=volume_ratio20,
                background20_status=('CURRENT_VOLUME_SOURCE_NOT_PANEL' if use_supplement_volume
                                     else 'KNOWN' if previous20_mean is not None else 'PARTIAL_UNKNOWN'),
                oversold_flag=oversold,
                oversold_close_le_80pct_prior60_high=oversold,
                volume_flag_5d_ge_1_5=volume_flag,
                high_volume_ratio_ge_1_5=volume_flag,
                oversold_rebound_watch=(bool(oversold and rebound_flag) if oversold is not None else None),
                strict_two_gate_oversold_5dvolume=strict,
                near_two_gate_one_missing=near_eligible,
                continuous_strength_highvolume_risk=False,
                history_source=('V4_SHARED_HK_0_2_PANEL_AUTHORITY_PLUS_PYTDX_CATEGORY4_SUPPLEMENT'
                                if use_supplement_volume or code in price_overlay_codes
                                else 'V4_SHARED_HK_0_2_PANEL_AUTHORITY'), history_adjustment='NONE',
                adjustment_consistency='PANEL_RAW_NO_ADJUSTMENT', near_failed_gate=failed_gate,
                near_failed_value=failed_value, near_gate_value=gate_value,
                near_gate_gap_ratio=gate_gap_ratio, near_gate_gap_value=gate_gap_value,
                source_refs=[dict(owner=panel['owner'], payload_path=panel['panel_path'],
                                  payload_sha256=panel['panel_sha256'],
                                  manifest_path=panel['panel_manifest_path'],
                                  manifest_sha256=panel['panel_manifest_sha256']),
                             dict(owner=master['owner'], payload_path=master['artifact_path'],
                                  payload_sha256=master['artifact_sha256'],
                                  manifest_path=master['manifest_path'],
                                  manifest_sha256=master['manifest_sha256']),
                             *sidecar_refs],
                volume_source=('PYTDX_EXHQ_CATEGORY_4_MARKET_71' if use_supplement_volume
                               else 'V4_SHARED_HK_0_2_PANEL_AUTHORITY'),
                volume_unit_status=volume_evidence['unit_status'],
                volume_scale_applied=volume_evidence['scale_applied'],
                volume_provenance=volume_evidence,
                research_boundary='RESEARCH_ONLY; no buy/sell/order conclusion',
            )
            # Return recent returns from the panel only when the exact rows are
            # available. These are background context, never a gate.
            ordered = code_history.sort_values('trade_date_compact')
            for periods, key in ((3, 'recent_3_session_return_pct'), (5, 'recent_5_session_return_pct')):
                if len(ordered) >= periods:
                    anchor = _screen_number(ordered.iloc[-periods]['close'], positive=True)
                    if anchor not in (None, 0) and close is not None:
                        row[key] = ((close / anchor) - 1.0) * 100.0
            rows.append(row)
        strict_rows = sorted((row for row in rows if row['strict_two_gate_oversold_5dvolume']),
                             key=lambda row: row['code'])
        near_rows = [row for row in rows if row['near_two_gate_one_missing']]
        near_rows.sort(key=lambda row: (float(row.get('near_gate_gap_ratio') or 0), row['code']))
        for rank, row in enumerate(strict_rows, 1):
            row['classification'] = 'STRICT_REBOUND'
            row['research_priority_method'] = 'TWO_GATE_STRICT'
            row['research_priority_rank'] = None
            row['reason_for_group'] = '收盘≤此前60个完整交易日最高价的80%且前5个完整交易日量比≥1.5；成交额与低点反弹仅作观察'
        for rank, row in enumerate(near_rows, 1):
            row['classification'] = 'NEAR_CONDITION'
            row['research_priority_method'] = 'TWO_GATE_ONE_MISS_NEAR'
            row['research_priority_rank'] = rank
            passed_gate = '60日超跌' if row['volume_flag_5d_ge_1_5'] is False else '前5日量比'
            failed_gate_label = '前5日量比≥1.5' if row['volume_flag_5d_ge_1_5'] is False else '收盘≤60日高点80%'
            row['reason_for_group'] = (f'剩余两项准入中仅{passed_gate}通过，{failed_gate_label}未通过；'
                                       '成交额与低点反弹仅作观察')
        pending = [row for row in rows if row['history_status'] != 'KNOWN']
        selected = [*strict_rows, *near_rows]
        selected_codes = {row['code'] for row in selected}
        pending_codes = {row['code'] for row in pending}
        excluded_rows = []
        unresolved_rows = []
        for row in rows:
            if row['code'] in selected_codes or row['code'] in pending_codes:
                continue
            decision = _screen_exclusion_decision(row)
            projected = dict(row, screen_decision=decision['status'],
                             exclusion_reason_code=decision['reason_code'],
                             reason_for_exclusion=decision['reason'],
                             research_priority_method='NO_RESEARCH_PRIORITY_OUTSIDE_STRICT_NEAR')
            if decision['status'] == 'EXCLUDED':
                projected['classification'] = 'EXCLUDED_REBOUND_SCREEN'
                excluded_rows.append(projected)
            else:
                projected['classification'] = 'UNRESOLVED_REBOUND_SCREEN'
                unresolved_rows.append(projected)
                gaps.append('SCREEN_ROW_EXCLUSION_UNRESOLVED:' + row['code'])
        excluded_rows.sort(key=lambda row: row['code'])
        unresolved_rows.sort(key=lambda row: row['code'])
        public_master = {key: value for key, value in master.items() if key != 'names'}
        authority = dict(panel_witness=panel, security_master=public_master,
                         source_contract=panel['source_contract'], amount_unit='HKD',
                         price_basis='RAW', session_kind='FULL_DAY_CLOSE',
                         volume_provenance=panel_volume_evidence)
        if supplement is not None:
            authority['daily_supplement'] = dict(
                status=supplement['status'], target_date=day,
                manifest_sha256=supplement['manifest_sha256'],
                raw_capture_sha256=supplement['raw_capture_sha256'],
                pointer_sha256=sidecar_refs[0]['pointer_sha256'],
                provider='PYTDX_EXHQ', category=4, market=71,
                volume_field='trade', volume_scale_applied=1,
                volume_unit_status='NOT_PROVEN',
                requested_sessions=[*previous5_session_dates, day],
            )
        identity = digest(dict(rule_version=REBOUND_SCREEN_RULE, target_trade_date=context.get('plan_trade_date'),
                               verified_session=day, panel_sha256=panel['panel_sha256'],
                               panel_manifest_sha256=panel['panel_manifest_sha256'],
                               security_master_manifest_sha256=master['manifest_sha256'],
                               oversold_ratio=_REBOUND_OVERSOLD_RATIO, prior_sessions=60,
                               prior60_session_dates=prior60_session_dates,
                               volume_gate=_REBOUND_VOLUME_GATE, previous_sessions=5,
                               previous5_full_session_dates=previous5_session_dates,
                               trading_calendar_sha256=history_sessions['calendar_sha256'],
                               screen_phase=context['screen_phase'],
                               screen_session_policy=context['screen_session_policy'],
                               volume_gate_policy='ORIGINAL_OWNER_UNIT_AND_SCALE_PROOF_REQUIRED',
                               observation_only=['amount_hkd', 'rebound_close_vs_low_pct']))
        coverage = dict(input_candidate_count=len(rows), history_complete_count=len(rows)-len(pending),
                        numeric_history_complete_count=sum(row['history_numeric_status'] == 'KNOWN' for row in rows),
                        history_pending_count=len(pending), strict_count=len(strict_rows),
                        near_candidate_count=len(near_rows), near_count=len(near_rows),
                        selected_count=len(selected), pending_codes=[row['code'] for row in pending],
                        panel_row_count=panel.get('panel_rows'), panel_code_count=panel.get('panel_code_count'),
                        excluded_count=len(excluded_rows), screen_unresolved_count=len(unresolved_rows),
                        row_accounted_count=(len(selected)+len(pending)+len(excluded_rows)+len(unresolved_rows)))
        gaps.extend('SCREEN_HISTORY_OR_VOLUME_INCOMPLETE:' + row['code'] for row in pending)
        status = 'READY_WITH_GAPS' if gaps else 'READY'
        decision_identity = digest(dict(input_identity=identity,
            excluded=[(row['code'], row['exclusion_reason_code'], row['close'],
                       row['oversold_cutoff_80pct_prior60_high'], row['volume_ratio_5d'])
                      for row in excluded_rows],
            unresolved=[(row['code'], row['exclusion_reason_code']) for row in unresolved_rows]))
        return dict(schema_version=REBOUND_SCREEN_SCHEMA, rule_version=REBOUND_SCREEN_RULE,
            target_trade_date=str(context.get('plan_trade_date') or ''), verified_session=day,
            status=status, cards=selected, strict=strict_rows, near=near_rows, pending=pending,
            excluded=excluded_rows, screen_unresolved=unresolved_rows, decision_identity=decision_identity,
            gaps=sorted(set(gaps)), coverage=coverage, input_identity=identity, authority=authority,
            data_context=_screen_data_context(context),
            RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False,
            main_screen_ready=True)
    except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        return _screen_empty(context, ['SCREEN_RECOMPUTE_FAILED:' + type(exc).__name__])


def read_plan_quotes(data_root: Path | None, context: Mapping[str, Any], *, authority_root: Path | None = None) -> dict:
    """Read original close rows, gated by the existing shared HK authority."""
    if data_root is None:
        return dict(quotes={},gaps=['PLAN_NATIVE_CLOSE_DATA_ROOT_NOT_BOUND'],verified=False)
    day=str(context['market_session'])
    try:
        from infrastructure.hkconnect_close_store import CloseSnapshotStore
        payload,sha=CloseSnapshotStore(Path(data_root)).read_snapshot(day)
        authority, authority_gaps = _read_hk02_panel_witness(authority_root, day)
        quotes={}
        for row in payload['rows']:
            # The original close schema has no unit/basis/session fields. The
            # shared HK 0.2 witness supplies those semantics without changing
            # the close payload or creating a second market producer.
            quote=dict(verification='OWNER_VERIFIED',symbol=row['code'],session_date=day,
                source_refs=[dict(owner='CloseSnapshotStore.read_snapshot',payload_path=f'hkconnect_close_snapshots/{day}.json',payload_sha256=sha)])
            if authority is not None:
                quote.update(currency=authority['price_currency'],price_basis=authority['price_basis'],
                    session_kind=authority['session_kind'],amount_unit=authority['amount_unit'],
                    authority_panel=authority,
                    source_refs=[*quote['source_refs'],dict(owner=authority['owner'],
                        payload_path=authority['panel_path'],payload_sha256=authority['panel_sha256'],
                        manifest_path=authority['panel_manifest_path'],manifest_sha256=authority['panel_manifest_sha256'])])
            else:
                quote.update(currency=row.get('currency',payload.get('currency')),
                    price_basis=row.get('price_basis',payload.get('price_basis')),
                    session_kind=row.get('session_kind',payload.get('session_kind')),
                    amount_unit=row.get('amount_unit',payload.get('amount_unit')))
            quote.update({k:row.get(k) for k in ('open','high','low','close','pre_close','amount')})
            checked=verified_quote(quote,row['code'],context)
            if checked:quotes[row['code']]=checked
        return dict(quotes=quotes,verified=bool(quotes),source_sha256=sha,
            source_date=day,raw_row_count=len(payload['rows']),verified_quote_count=len(quotes),
            authority_panel_witness=authority,
            gaps=sorted(set(authority_gaps + ([] if len(quotes)==len(payload['rows']) else ['PLAN_CLOSE_PRICE_UNIT_BASIS_OR_SESSION_CONTRACT_MISSING'])))
                )
    except (ImportError,OSError,ValueError,TypeError,KeyError,RuntimeError) as exc:
        return dict(quotes={},verified=False,gaps=['PLAN_NATIVE_CLOSE_READ_FAILED:'+day+':'+type(exc).__name__])


def stock_plan(stock: Mapping[str, Any], context: Mapping[str, Any], *, quote: Mapping[str, Any] | None = None,
               late_tail_observation: Mapping[str, Any] | None = None) -> dict:
    """Different issuer evidence => explicit different verification plans.

    Only issuer-local propositions select review questions; full mixed paragraphs
    cannot select a domain template. Price questions bind separately to the
    original verified market fields and never imply an executed order.
    """
    symbol=str(stock['symbol']); name=str(stock.get('name') or symbol)
    tail_reference = None
    if isinstance(late_tail_observation, Mapping):
        tail_observation = late_tail_observation.get('observation')
        tail_available = timestamp(late_tail_observation.get('available_at'))
        tail_observed = timestamp(late_tail_observation.get('observed_at'))
        cutoff = timestamp(context.get('research_cutoff'))
        if (canonical_symbol(late_tail_observation.get('symbol'), 'HK_CONNECT') == symbol
                and late_tail_observation.get('status') == 'AVAILABLE_BEFORE_CUTOFF'
                and late_tail_observation.get('observation_type') == 'PYTDX_EXHQ_MINUTE_STAGE_OBSERVATION'
                and late_tail_observation.get('provider') == 'pytdx_exhq'
                and late_tail_observation.get('stage_id') == 'STAGE_1545_1555'
                and late_tail_observation.get('source_trade_date') == context.get('market_session')
                and late_tail_observation.get('plan_trade_date') == context.get('plan_trade_date')
                and isinstance(tail_observation, Mapping)
                and tail_observation.get('candidate_status') == 'OBSERVATION_ONLY'
                and tail_available and tail_observed and cutoff
                and tail_observed <= tail_available <= cutoff):
            tail_reference = dict(late_tail_observation)
    from .workspace_actions import proposition_actions
    semantic=proposition_actions(stock)
    evidence=semantic['clean_evidence']
    actions=semantic['actions']
    ids=list(dict.fromkeys(eid for action in actions for eid in action['evidence_ids']))
    selected=semantic['evidence_rules']
    conditions=[a['text'] for a in actions if a['type']=='WATCH']
    risk=[a['text'] for a in actions if a['type']=='WAIT']
    invalid=[a['text'] for a in actions if a['type']=='INVALIDATE']
    base_action_texts={a['text'] for a in actions}
    missing=['目标日港股通资格须独立核验']
    if stock.get('connect_eligibility')=='VERIFIED_TARGET_UNIVERSE':missing=[]
    criteria={k:dict(status='UNKNOWN',reason=reason) for k,reason in {
        'turnover_gt_100m_hkd':'缺最近完整港股交易日累计成交额及HKD单位',
        'volume_expansion':'缺同口径20个完整交易日成交量均值；不能用涨幅替代量比',
        'oversold_repair':'缺至少20日同口径价格路径及修复确认；单日下跌不能判为超跌',
        'continuous_strength':'缺至少4个连续完整交易日同口径收盘价',
        'high_volume_risk':'缺历史成交量/价格位置及实际自由流通分母'} .items()}
    checked=verified_quote(quote,symbol,context)
    trigger=invalid_price=None;provenance=None
    wait=list(dict.fromkeys(a['text'] for a in actions if a['type'] in {'WAIT','NO_CHASE'}))
    if checked:
        trigger=checked['close'];invalid_price=checked.get('low')
        provenance=dict(symbol=symbol,session_date=checked['session_date'],currency='HKD',price_basis=checked['price_basis'],
            verification='OWNER_VERIFIED',session_kind='FULL_DAY_CLOSE',source_refs=checked['source_refs'],
            authority_panel=checked.get('authority_panel'),
            rule_id='RECLAIM_VERIFIED_SESSION_CLOSE',trigger_formula='close',invalidation_formula='low' if invalid_price else None,
            inputs={k:checked.get(k) for k in ('close','low','high','pre_close')}, semantics='REFERENCE_LEVEL_NOT_ORDER_OR_EXECUTED_SIGNAL')
        conditions.append(f'价格确认路径：以{checked["session_date"]}原始收盘{trigger:g}港元为收复/守稳参考；目标日需另验承接与成交，数值本身不触发订单。')
        if invalid_price is not None:
            invalid.append(f'跌破同口径前完整交易日低点{invalid_price:g}港元且不能收复时，撤销该参考位计划；不是实际卖出指令。')
        else:missing.append('前完整交易日低点缺失，不能计算数值失效位')
        if checked.get('amount') is not None and checked.get('amount_unit')=='HKD':
            amount=checked['amount']
            criteria['turnover_gt_100m_hkd']=dict(status='PASS' if amount>100_000_000 else 'FAIL',value=amount,unit='HKD',
                operator='>',threshold=100_000_000,session_date=checked['session_date'],source_refs=checked['source_refs'])
            if amount<=100_000_000:wait.append('参考日累计成交额未严格超过1亿港元，流动性条件不通过。')
    else:
        missing.append('缺已核验最近完整HK交易日的币种/复权口径/收盘数据；不提供数值触发位')
        conditions.append('待原行情owner补齐最近完整HK交易日收盘/高低点及口径后：分别观察回踩守稳或放量突破，不能凭此卡宣称已经确认。')
    if checked:
        market_id='market:'+digest([symbol,checked['session_date'],checked['source_refs']])
        market_quote=json.dumps({k:checked.get(k) for k in ('symbol','session_date','close','low','amount','amount_unit')},ensure_ascii=False,sort_keys=True)
        support=dict(evidence_id=market_id,proposition_id=market_id,symbol=symbol,
            quote=market_quote,source_field='verified_market_fields',start=0,end=len(market_quote),
            support_kind='VERIFIED_MARKET_FIELDS',source_refs=checked['source_refs'])
        for kind,texts in (('WATCH',conditions),('INVALIDATE',invalid),('WAIT',wait)):
            for text in texts:
                if text in base_action_texts:continue
                actions.append(dict(action_id=digest([market_id,kind,text]),type=kind,text=text,
                    rule_id='VERIFIED_FULL_DAY_PRICE_REFERENCE',evidence_ids=[market_id],proposition_ids=[market_id],
                    supporting_quotes=[support],assertion_type='RESEARCH_CONDITION_NOT_OBSERVED_FACT',orders_sent=False))
    missing.extend(c['reason'] for c in criteria.values() if c['status']=='UNKNOWN')
    if any(not timestamp(e.get('available_at')) for e in evidence):missing.append('部分材料缺可用时间；本次读到不证明历史PIT捕获')
    for e in evidence:
        text=('本条为窗口前背景材料，不能当成当前窗口新增催化。' if e.get('temporal_role')=='BACKGROUND' else
              '本条发布时间未知，不能计入新增催化。' if e.get('temporal_role')=='PUBLICATION_UNKNOWN' else None)
        if text and e.get('propositions'):
            p=e['propositions'][0]
            support={k:p[k] for k in ('evidence_id','proposition_id','symbol','quote','source_field','start','end')}
            actions.append(dict(action_id=digest([p['proposition_id'],'TEMPORAL',text]),type='WAIT',text=text,
                rule_id='EVIDENCE_TIME_BOUNDARY',evidence_ids=[p['evidence_id']],proposition_ids=[p['proposition_id']],
                supporting_quotes=[support],assertion_type='RESEARCH_CONDITION_NOT_OBSERVED_FACT',orders_sent=False))
    # These arrays are the visible projection of bound actions, never a second
    # untraceable template path. Missing inputs stay in missing, not as signals.
    actions=list({a['action_id']:a for a in actions}.values())
    conditions=[a['text'] for a in actions if a['type']=='WATCH']
    invalid=[a['text'] for a in actions if a['type']=='INVALIDATE']
    wait=list(dict.fromkeys(a['text'] for a in actions if a['type'] in {'WAIT','NO_CHASE'}))
    risk=list(dict.fromkeys(a['text'] for a in actions if a['type']=='WAIT'))
    ids=sorted({eid for a in actions for eid in a['evidence_ids']})
    return dict(trigger_price=trigger,invalidation_price=invalid_price,price_provenance=provenance,
        late_tail_observation=tail_reference,
        next_observation=conditions,wait_conditions=wait,key_risks=list(dict.fromkeys(risk)),invalidation_conditions=invalid,
        actions=actions,rejected_relation_count=len(semantic['rejected_relations']),
        missing=list(dict.fromkeys(missing)),evidence_ids=ids,evidence_rules=selected,evidence_count=len(evidence),
        criteria=criteria,plan_trade_date=context.get('plan_trade_date'),research_cutoff=context.get('research_cutoff'),
        market_session=context.get('market_session'),execution_scope='RESEARCH_ONLY',qualified=False,**FLAGS)
