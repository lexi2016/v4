"""Read exact, saved US close evidence for the workbench's observation day."""
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from math import isfinite
import re
from zoneinfo import ZoneInfo

from contracts.us_equity_calendar import CALENDAR_PATH, latest_completed_session


SHANGHAI = ZoneInfo('Asia/Shanghai')
# The workbench's formal pre-open delivery in plan_9.
PREOPEN_DEADLINE = time(8, 10)
BENCHMARK_NAMES = {'.DJI': '道指', '.SPX': '标普500', '.IXIC': '纳指'}
BENCHMARK_URLS = {
    '.DJI': 'https://www.futunn.com/index/.DJI-US',
    '.SPX': 'https://www.futunn.com/index/.SPX-US',
    '.IXIC': 'https://www.futunn.com/index/.IXIC-US?security_id=23',
}


def us_context_dates(observation, now):
    if now.utcoffset() is None:
        raise ValueError('WORKBENCH_US_CLOCK_TIMEZONE_REQUIRED')
    deadline = datetime.combine(date.fromisoformat(observation), PREOPEN_DEADLINE, SHANGHAI)
    cutoff = min(deadline, now.astimezone(SHANGHAI))
    latest = latest_completed_session(deadline)
    close = latest.close_at
    return dict(
        us_session_date=latest.session_date, session_close_at=close.isoformat(),
        capture_research_date=(close + timedelta(minutes=15)).astimezone(SHANGHAI).strftime('%Y%m%d'),
        context_cutoff_at=cutoff.isoformat(),
        session_completed=close <= cutoff,
    )


def _timestamp(value):
    text = datetime.fromisoformat(value)
    if text.utcoffset() is None:
        raise ValueError('WORKBENCH_US_TIMESTAMP_TIMEZONE_REQUIRED')
    return text


def _number(value):
    return type(value) in (int, float) and isfinite(value)


def standalone_benchmarks(reference, observation, dates, *, checked, checked_bytes, flags):
    """Bind the owner receipt and saved provider pages before projecting."""
    receipt = checked(reference)
    if (receipt.get('schema') != 'V4_WORKBENCH_US_BENCHMARKS_V1'
            or receipt.get('status') not in {'DATED_US_BENCHMARKS', 'PARTIAL'}
            or receipt.get('provider') != 'Futu official website'
            or receipt.get('us_session_date') != dates['us_session_date']
            or receipt.get('session_close_at') != dates['session_close_at']
            or receipt.get('market_context_research_date') != dates['capture_research_date']
            or date.fromisoformat(receipt['observation_date']) > date.fromisoformat(observation)
            or any(receipt.get(key) is not value for key, value in flags.items())):
        raise ValueError('WORKBENCH_US_BENCHMARK_RECEIPT_IDENTITY_CONFLICT')
    cutoff = _timestamp(dates['context_cutoff_at'])
    close = _timestamp(dates['session_close_at'])
    recorded = _timestamp(receipt['recorded_at'])
    if not close <= recorded <= cutoff:
        raise ValueError('WORKBENCH_US_BENCHMARK_NOT_AVAILABLE_AT_CUTOFF')
    if checked_bytes(receipt['calendar_ref']) != CALENDAR_PATH.read_bytes():
        raise ValueError('WORKBENCH_US_BENCHMARK_CALENDAR_CONFLICT')
    raw = checked(receipt['raw_ref'])
    pages = raw['pages']
    rows = receipt['rows']
    if (not isinstance(pages, dict) or not isinstance(rows, list)
            or len(rows) != len(BENCHMARK_NAMES) or {r['symbol'] for r in rows} != set(BENCHMARK_NAMES)):
        raise ValueError('WORKBENCH_US_BENCHMARK_ROW_IDENTITY_CONFLICT')
    projected = []
    for row in rows:
        if row.get('status') != 'DATED_CLOSE':
            continue
        code = row['symbol']
        page = pages[code]
        value, previous, change = (row[key] for key in ('value', 'previous_close', 'change_pct'))
        read_at = _timestamp(row['read_at'])
        if (row.get('name') != BENCHMARK_NAMES[code] or row.get('timezone') != 'America/New_York'
                or row.get('session_date') != dates['us_session_date']
                or row.get('source_asof') != dates['session_close_at']
                or not close <= read_at <= recorded
                or not all(map(_number, (value, previous, change))) or value <= 0 or previous <= 0
                or abs((value / previous - 1) * 100 - change) > .015
                or row.get('source_url') != BENCHMARK_URLS[code] or page.get('url') != BENCHMARK_URLS[code]
                or page.get('read_at') != row.get('read_at') or page.get('sha256') != row.get('raw_sha256')
                or not re.fullmatch('[a-f0-9]{64}', row['raw_sha256'])
                or sha256(page['html'].encode('utf-8')).hexdigest() != row['raw_sha256']):
            raise ValueError('WORKBENCH_US_BENCHMARK_PAGE_OR_ROW_CONFLICT:' + code)
        projected.append(row)
    if not projected or (receipt['status'] == 'DATED_US_BENCHMARKS' and len(projected) != len(BENCHMARK_NAMES)):
        raise ValueError('WORKBENCH_US_BENCHMARK_COVERAGE_CONFLICT')
    return dict(
        schema=receipt['schema'], status=receipt['status'], observation_date=observation,
        source_observation_date=receipt['observation_date'], us_session_date=dates['us_session_date'],
        session_close_at=dates['session_close_at'], market_context_research_date=dates['capture_research_date'],
        provider=receipt['provider'], recorded_at=receipt['recorded_at'], rows=projected,
        calendar_ref=receipt['calendar_ref'], raw_ref=receipt['raw_ref'], receipt_ref=reference, **flags,
    )
