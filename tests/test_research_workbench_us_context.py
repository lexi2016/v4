import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from infrastructure.research_workbench_host import FLAGS, ResearchWorkbenchHost
from infrastructure.research_workbench_us_context import BENCHMARK_NAMES, BENCHMARK_URLS, CALENDAR_PATH


OBSERVATION = '2026-11-16'
CURRENT = '2026-11-14T13:00:00+08:00'
CLOSE = '2026-11-13T16:00:00-05:00'
READ = '2026-11-14T12:30:00+08:00'


def ref(path):
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def put(path, value):
    path.write_text(json.dumps(value))
    return ref(path)


def workbench(tmp_path, *, current=CURRENT, **changes):
    rows = []
    pages = {}
    for code, name in BENCHMARK_NAMES.items():
        raw = f'<html>{code}</html>'
        digest = hashlib.sha256(raw.encode()).hexdigest()
        pages[code] = dict(url=BENCHMARK_URLS[code], html=raw, sha256=digest, read_at=READ)
        rows.append(dict(symbol=code, name=name, value=101, previous_close=100, change_pct=1,
                         source_asof=CLOSE, timezone='America/New_York', session_date='20261113',
                         source_url=BENCHMARK_URLS[code], read_at=READ, raw_sha256=digest, status='DATED_CLOSE'))
    raw = put(tmp_path / 'raw.json', {'pages': pages})
    receipt = dict(schema='V4_WORKBENCH_US_BENCHMARKS_V1', observation_date=OBSERVATION,
                   status='DATED_US_BENCHMARKS', rows=rows, recorded_at=READ,
                   provider='Futu official website', us_session_date='20261113', session_close_at=CLOSE,
                   calendar_ref=ref(CALENDAR_PATH.resolve()), market_context_research_date='20261114', raw_ref=raw, **FLAGS)
    receipt.update(changes)
    result = put(tmp_path / 'benchmarks.json', receipt)
    host = ResearchWorkbenchHost.__new__(ResearchWorkbenchHost)
    host.skill_r2 = None
    host.binding = {'us_benchmarks': {'20261113': result}}
    host._clock = lambda: datetime.fromisoformat(current)
    host._observation_date = lambda _: OBSERVATION
    host._view = lambda *_: {'source_generation': 'test', 'source_identity': {'input_sha256': 'test'}}
    return host


def test_weekend_close_without_a_share_snapshot_is_exact_and_keeps_dates(tmp_path):
    host = workbench(tmp_path)
    result = host.source_context('2026-11-13')
    assert result['source_date'] == '2026-11-13' and result['observation_date'] == OBSERVATION
    assert result['us_context'] == dict(
        status='SESSION_BOUND', us_session_date='20261113', session_close_at=CLOSE,
        capture_research_date='20261114', context_cutoff_at=CURRENT, session_completed=True,
    )
    assert result['us_benchmarks']['observation_date'] == OBSERVATION
    assert len(result['us_benchmarks']['rows']) == 3
    assert 'market_context' not in result['us_benchmarks']
    assert result['markets']['JP']['status'] == 'UNKNOWN'


def test_regular_date_and_before_expected_close_never_use_another_us_session(tmp_path):
    host = workbench(tmp_path)
    regular = host._standalone_us_context('2026-11-13')
    assert regular['us_context']['capture_research_date'] == '20261113'
    assert regular['us_context']['us_session_date'] == '20261112'
    assert regular['us_context']['context_cutoff_at'] == '2026-11-13T08:10:00+08:00'
    assert 'us_benchmarks' not in regular
    host._clock = lambda: datetime.fromisoformat('2026-11-14T04:59:59+08:00')
    early = host._standalone_us_context(OBSERVATION)
    assert early['us_context']['status'] == 'WAITING_FOR_EXPECTED_US_CLOSE'
    assert early['us_context']['us_session_date'] == '20261113'
    assert 'us_benchmarks' not in early


@pytest.mark.parametrize('changed,value', [
    ('us_session_date', '20261112'),
    ('market_context_research_date', '20261116'),
    ('observation_date', '2026-11-17'),
    ('recorded_at', '2026-11-14T13:00:01+08:00'),
    ('production_allowed', True),
])
def test_rejects_wrong_date_or_late_or_unsafe_receipt(tmp_path, changed, value):
    host = workbench(tmp_path, **{changed: value})
    result = host._standalone_us_context(OBSERVATION)
    assert result['us_context']['benchmark_status'] == 'CANNOT_CONFIRM'
    assert 'us_benchmarks' not in result


def test_rejects_saved_page_sha_drift(tmp_path):
    host = workbench(tmp_path)
    raw = tmp_path / 'raw.json'
    obj = json.loads(raw.read_bytes())
    obj['pages']['.SPX']['html'] = 'mutated'
    receipt = tmp_path / 'benchmarks.json'
    changed = json.loads(receipt.read_bytes())
    changed['raw_ref'] = put(raw, obj)
    host.binding['us_benchmarks']['20261113'] = put(receipt, changed)
    result = host._standalone_us_context(OBSERVATION)
    assert 'PAGE_OR_ROW_CONFLICT:.SPX' in result['us_context']['benchmark_reason']
    assert 'us_benchmarks' not in result
