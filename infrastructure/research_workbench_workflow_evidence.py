"""Read the SHA-bound observation evidence for the existing V4 workbench."""
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
import re
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo('Asia/Shanghai')
SCHEMA = 'V4_WORKBENCH_NODE_EVIDENCE_V1'
UNCONFIRMED = 'CANNOT_CONFIRM_NO_RECEIPT'
BAD_RECEIPT = 'CANNOT_CONFIRM_BAD_RECEIPT'
OBSERVED = {'COMPLETED', 'PARTIAL', 'BLOCKED', 'FAILED', 'EXPIRED', 'MISSED'}
UNOBSERVED = {UNCONFIRMED, 'DEFERRED_USER', 'NOT_DUE'}
SOURCE_ERRORS = (ValueError, OSError, KeyError, TypeError)

# These existing Stage windows supplement the original plan's time prose.
PLAN_TIMES = {
    12: '港股 09:20 二筛／A 股 09:25 撮合后／两市 09:30 后',
    13: '09:30–09:35、09:35–09:40、09:40–09:45、09:45–10:30、13:00–13:15、14:45–15:00；午休核验',
    16: '港股 15:45–15:55 尾盘／16:00 后及收市竞价后',
    17: '16:10、16:40 重试／17:00 告警',
}
FIRST_MARKET_WINDOW = {11: '09:00', 12: '09:20', 16: '15:45'}
NEXT_POOL_STAGE = {
    'id': 21,
    'time_bjt': '21:15',
    'name': '次日预选池归档',
    'action': '沿原复盘归档链分别核对 A 股复盘继续观察池和 Stage7 分时池，保留来源日、次日目标交易日、原始证据及各自的回执。',
    'outputs': '复盘继续观察池／Stage7 分时池',
}
GROUPS = (
    ('夜间研究', '01:00:00', '03:00:00'),
    ('海外验证', '03:00:00', '06:30:00'),
    ('盘前交付', '06:30:00', '08:50:00'),
    ('盘中观察', '08:50:00', '15:00:00'),
    ('收盘复盘', '15:00:00', '23:59:59'),
)


def planned_times(item):
    original = item['time_bjt']
    text = PLAN_TIMES.get(item['id'], original)
    match = re.match(r'^(\d\d:\d\d)(?:[—–](\d\d:\d\d))?', text)
    end = match.group(2) if match else None
    start = match.group(1) if match else FIRST_MARKET_WINDOW.get(item['id'])
    if '截止' in original or original.endswith('前'):
        end, start = start, None
    return dict(
        planned_time_zh=text,
        planned_start_local=start + ':00' if start else None,
        planned_end_local=end + ':00' if end else None,
    )


def bound_projection(value, source_date, observation_date, next_target_date):
    if (not isinstance(value, dict) or value.get('schema') != SCHEMA
            or value.get('source_date') != source_date or value.get('observation_date') != observation_date
            or value.get('next_target_date') != next_target_date or not next_target_date
            or not isinstance(value.get('nodes'), dict)
            or set(value['nodes']) - {str(number) for number in range(1, 22)}):
        raise ValueError('WORKBENCH_NODE_EVIDENCE_IDENTITY_CONFLICT')
    return value


def file_revision(path):
    """File metadata is an invalidation hint. The read endpoint checks SHA."""
    try:
        stat = Path(path).lstat()
    except OSError as error:
        return ('UNAVAILABLE', error.errno)
    return (stat.st_dev, stat.st_ino, stat.st_mode, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def original_references(nodes, preopen_input=None):
    """List the original paths named in the small, pinned descriptor."""
    if not isinstance(nodes, dict):
        raise ValueError('WORKBENCH_NODE_EVIDENCE_NODES_INVALID')
    records = [*nodes.values(), preopen_input]
    paths = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        events = record.get('events')
        for item in [record, *(events if isinstance(events, list) else [])]:
            refs = item.get('evidence') if isinstance(item, dict) else None
            for ref in refs if isinstance(refs, list) else ():
                if isinstance(ref, dict) and isinstance(ref.get('path'), str):
                    paths.add(ref['path'])
    return paths


def _text(value, field, *, required=False):
    text = value.get(field)
    if text is None and not required:
        return None
    if not isinstance(text, str) or not text.strip():
        raise ValueError('WORKBENCH_NODE_EVIDENCE_TEXT_INVALID:' + field)
    return text


def _list(value, field):
    items = value.get(field, [])
    if not isinstance(items, list):
        raise ValueError('WORKBENCH_NODE_EVIDENCE_LIST_INVALID:' + field)
    return items


def _time(value, field, now, dated=None, *, overnight=False):
    text = _text(value, field)
    if text is None:
        return None
    instant = datetime.fromisoformat(text)
    if instant.utcoffset() is None or instant > now:
        raise ValueError('WORKBENCH_NODE_EVIDENCE_TIME_INVALID:' + field)
    local_date = instant.astimezone(SHANGHAI).date()
    if dated is not None and local_date != dated and not (overnight and local_date == dated + timedelta(days=1)):
        raise ValueError('WORKBENCH_NODE_EVIDENCE_DATE_CONFLICT:' + field)
    return instant.astimezone(SHANGHAI).isoformat()


def _material(value):
    if not isinstance(value, dict):
        raise ValueError('WORKBENCH_NODE_MATERIAL_INVALID')
    label = _text(value, 'label', required=True)
    url = _text(value, 'url', required=True)
    parsed = urlsplit(url)
    path = unquote(parsed.path)
    if (parsed.scheme or parsed.netloc or '\\' in path or path.startswith('//')
            or any(ord(char) < 32 for char in url + path)
            or '%' in path or '..' in PurePosixPath(path).parts
            or not path.startswith(('/api/v4/', '/api/v3/', '/research-panel/'))):
        raise ValueError('WORKBENCH_NODE_MATERIAL_PATH_INVALID')
    return dict(label=label, url=url)


def _record(value, dated, now, checked_bytes, *, event, overnight):
    if not isinstance(value, dict):
        raise ValueError('WORKBENCH_NODE_EVIDENCE_RECORD_INVALID')
    status = _text(value, 'status', required=True)
    if status not in OBSERVED | UNOBSERVED:
        raise ValueError('WORKBENCH_NODE_EVIDENCE_STATUS_INVALID')
    missing = _list(value, 'missing')
    if any(not isinstance(reason, str) or not reason.strip() for reason in missing):
        raise ValueError('WORKBENCH_NODE_EVIDENCE_MISSING_INVALID')
    evidence = _list(value, 'evidence')
    for ref in evidence:
        checked_bytes(ref)
    return dict(
        status=status,
        result=_text(value, 'result'),
        recorded_at=_time(value, 'recorded_at', now, dated, overnight=overnight),
        source_asof=_time(value, 'source_asof', now),
        missing=missing,
        error=_text(value, 'error'),
        materials=[_material(item) for item in _list(value, 'materials')],
        evidence=[dict(path=ref['path'], sha256=ref['sha256']) for ref in evidence],
        **(dict(label=_text(value, 'label', required=True)) if event else {}),
    )


def checked_event(value, dated, now, checked_bytes, *, overnight=False):
    event = _record(value, dated, now, checked_bytes, event=True, overnight=overnight)
    if event['status'] in OBSERVED and not event['evidence']:
        raise ValueError('WORKBENCH_NODE_EVENT_EVIDENCE_MISSING')
    return event


def checked_node(value, dated, now, checked_bytes, *, overnight=False):
    node = _record(value, dated, now, checked_bytes, event=False, overnight=overnight)
    events = []
    for entry in _list(value, 'events'):
        try:
            event = checked_event(entry, dated, now, checked_bytes, overnight=overnight)
        except SOURCE_ERRORS as error:
            label = entry.get('label') if isinstance(entry, dict) else None
            event = dict(label=label or '原回执', status=BAD_RECEIPT, error=str(error))
        events.append(event)
    node['events'] = events
    if any(event['status'] == BAD_RECEIPT for event in events):
        has_valid_evidence = node['evidence'] or any(
            event['evidence'] for event in events if event['status'] in OBSERVED
        )
        node['status'] = 'PARTIAL' if has_valid_evidence else BAD_RECEIPT
        node['result'] = None
    if node['status'] in OBSERVED and not (
        node['evidence'] or any(event.get('evidence') for event in events if event['status'] in OBSERVED)
    ):
        raise ValueError('WORKBENCH_NODE_RESULT_EVIDENCE_MISSING')
    return node
