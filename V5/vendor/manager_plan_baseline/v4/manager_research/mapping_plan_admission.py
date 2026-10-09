"""Admission inside one original workspace computation, before saved-plan overlay."""
import re
from collections.abc import Mapping
from datetime import datetime


def aware(value):
    if not isinstance(value, str):
        raise ValueError('DAILY_MAPPING_TIME_INVALID')
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('DAILY_MAPPING_TIMEZONE_REQUIRED')
    return result


def rejection_reason(daily, date, context, current):
    """A previous mapping is reference-only unless its exact source still applies.

    Daily and plan cutoffs/identities need not be equal. The original daily
    generated_at loses microseconds, so there is deliberately no Cd <= G test.
    """
    try:
        cp = aware(context.get('research_cutoff'))
        cd = aware(daily.get('research_cutoff'))
        generated = aware(daily.get('generated_at'))
    except (ValueError, TypeError):
        return 'DAILY_MAPPING_TIME_UNVERIFIED'
    if generated > cp:
        return 'DAILY_MAPPING_NOT_AVAILABLE_AT_PLAN_CUTOFF'
    if cd > cp:
        return 'DAILY_MAPPING_RESEARCH_CUTOFF_AFTER_PLAN'
    if daily.get('target_trade_date') != date or context.get('plan_trade_date') != date:
        return 'DAILY_MAPPING_TARGET_MISMATCH'
    try:
        from contracts.us_equity_calendar import latest_completed_session
        expected = latest_completed_session(cp).session_date
        produced = latest_completed_session(cd).session_date
    except (ValueError, TypeError, OSError, ImportError):
        return 'DAILY_MAPPING_SESSION_UNVERIFIED'
    if daily.get('us_session_date') != expected or produced != expected:
        return 'DAILY_MAPPING_SESSION_MISMATCH'
    if (daily.get('status') not in {'COMPLETED', 'VALID_EMPTY'}
            or daily.get('source_status') != 'READY'
            or not isinstance(current, Mapping) or current.get('status') != 'READY'):
        return 'DAILY_MAPPING_CURRENT_SOURCE_NOT_READY'
    try:
        if aware(current.get('research_cutoff')) != cp:
            return 'DAILY_MAPPING_CURRENT_SOURCE_CONTEXT_MISMATCH'
    except (ValueError, TypeError):
        return 'DAILY_MAPPING_CURRENT_SOURCE_CONTEXT_MISMATCH'
    if current.get('target_trade_date') != date or current.get('expected_us_session') != expected:
        return 'DAILY_MAPPING_CURRENT_SOURCE_SESSION_MISMATCH'
    saved, source = daily.get('source_identity'), current.get('source_identity')
    if not isinstance(saved, Mapping) or not isinstance(source, Mapping):
        return 'DAILY_MAPPING_SOURCE_IDENTITY_UNVERIFIED'
    fields = dict(owner='ResearchPeripheralStore', source='external_finance', status='VERIFIED',
        session_date=expected, payload_path=f'research/peripherals/{expected}/external_finance.json',
        receipt_path=f'receipts/research/peripherals/{expected}/external_finance.json',
        manifest_path='research/peripherals/manifest.json')
    if any(saved.get(key) != value or source.get(key) != value for key, value in fields.items()):
        return 'DAILY_MAPPING_SOURCE_IDENTITY_MISMATCH'
    for key in ('payload_sha256', 'receipt_sha256', 'manifest_sha256'):
        if not re.fullmatch('[0-9a-f]{64}', str(saved.get(key) or '')) or source.get(key) != saved[key]:
            return 'DAILY_MAPPING_SOURCE_EVIDENCE_CHANGED:' + key
    if not re.fullmatch('[0-9a-f]{64}', str(daily.get('artifact_sha256') or '')):
        return 'DAILY_MAPPING_ARTIFACT_IDENTITY_UNVERIFIED'
    return None
