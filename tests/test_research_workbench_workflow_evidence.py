"""Regression checks for date-bound Workbench nodes and original receipts."""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from infrastructure import research_workbench_host
from infrastructure.research_workbench_host import FLAGS, ResearchWorkbenchHost


SOURCE = '2026-11-12'
OBSERVATION = '2026-11-13'
NEXT_TARGET = '2026-11-16'
NOW = datetime.fromisoformat('2026-11-13T22:59:00+08:00')


def pinned(path, value):
    data = json.dumps(value).encode()
    path.write_bytes(data)
    return dict(path=str(path), sha256=sha256(data).hexdigest())


def projection(source=SOURCE, observation=OBSERVATION, target=NEXT_TARGET, **fields):
    return dict(
        schema='V4_WORKBENCH_NODE_EVIDENCE_V1',
        source_date=source, observation_date=observation, next_target_date=target, nodes={},
    ) | fields


def host_fixture(tmp_path, **extra):
    stage_times = {
        5: '海外验证完成—06:30', 7: '07:00—08:00，持续补至08:10', 9: '08:10 截止',
        11: '港股09:00／A股09:15', 20: '各产物节点；19:00—次日01:00',
    }
    stages = [dict(id=i, name=f'节点 {i}', time_bjt=stage_times.get(i, '01:00—02:00'), action='计划动作')
              for i in range(1, 21)]
    calendar = Path(__file__).resolve().parents[1] / 'contracts' / 'market_calendar_2026.json'
    plan = pinned(tmp_path / 'plan.json', dict(stages=stages))
    binding = dict(
        schema='V4_MAC_WORKBENCH_BINDING_V1', workflow_plan=plan, workflow_date='2026-10-30',
        calendar=dict(path=str(calendar), sha256=sha256(calendar.read_bytes()).hexdigest()),
        **FLAGS,
    ) | extra
    # The workflow reader only needs its binding and clock. The unrelated
    # classification reader is supplied by the exact installed API role.
    host = ResearchWorkbenchHost.__new__(ResearchWorkbenchHost)
    host.binding = binding
    host._clock = lambda: NOW
    return host


def nodes(workflow):
    return {item['id']: item for item in workflow['time_contract']['nodes']}


def test_separate_main_retry_expiry_and_alert_and_keep_full_time_windows(tmp_path):
    primary = pinned(tmp_path / 'primary.json', dict(status='FAILED'))
    retry = pinned(tmp_path / 'retry.json', dict(status='PARTIAL'))
    expired = pinned(tmp_path / 'expired.json', dict(status='EXPIRED'))
    ref = pinned(tmp_path / 'projection.json', projection(nodes={
        '15': dict(status='FAILED', result='日期或代次冲突', recorded_at='2026-11-13T15:40:17+08:00', evidence=[primary]),
        '17': dict(status='PARTIAL', events=[
            dict(label='16:10 重试', status='PARTIAL', result='5570/5842', recorded_at='2026-11-13T17:27:00+08:00', evidence=[retry]),
            dict(label='16:40 重试', status='EXPIRED', recorded_at='2026-11-13T17:00:00+08:00', evidence=[expired]),
            dict(label='17:00 阻塞告警', status='CANNOT_CONFIRM_NO_RECEIPT', missing=['原告警回执待核']),
        ]),
    }))
    view = host_fixture(tmp_path, workflow_node_evidence={OBSERVATION: ref}).workflow(SOURCE)
    rows = nodes(view)
    assert list(rows) == [f'plan_{number}' for number in range(1, 22)]
    assert rows['plan_21']['planned_time_zh'] == '21:15'
    assert rows['plan_9']['planned_time_zh'] == '08:10 截止'
    assert rows['plan_9']['planned_start_local'] is None
    assert rows['plan_9']['planned_end_local'] == '08:10:00'
    assert rows['plan_7']['planned_time_zh'] == '07:00—08:00，持续补至08:10'
    assert '14:45–15:00' in rows['plan_13']['planned_time_zh']
    assert view['source_date'] == SOURCE and view['observation_date'] == OBSERVATION and view['next_target_date'] == NEXT_TARGET
    assert rows['plan_15']['execution_status'] == 'FAILED'
    assert rows['plan_15']['recorded_at'] == '2026-11-13T15:40:17+08:00'
    assert rows['plan_15']['execution_evidence'] == [primary]
    actual_events = rows['plan_17']['events']
    assert [event['status'] for event in actual_events] == ['PARTIAL', 'EXPIRED', 'CANNOT_CONFIRM_NO_RECEIPT']
    assert [event['evidence'] for event in actual_events] == [[retry], [expired], []]


def test_future_only_reads_distinct_preopen_input_and_default_has_no_old_receipts(tmp_path):
    material = pinned(tmp_path / 'handoff.json', dict(count=392))
    ref = pinned(tmp_path / 'projection.json', projection(OBSERVATION, NEXT_TARGET, '2026-11-17', nodes={
        '19': dict(status='COMPLETED', result='未来节点不得显示', evidence=[material]),
    }, preopen_input=dict(
        label='收盘数值候选', status='COMPLETED', recorded_at='2026-11-13T18:57:00+08:00',
        result='392 只', evidence=[material],
    )))
    old = pinned(tmp_path / 'old.json', dict(observation_date='2026-10-30', nodes={'1': dict(status='COMPLETED')}))
    host = host_fixture(tmp_path, workflow_node_evidence={NEXT_TARGET: ref}, workflow_execution=old)
    future = host.workflow(OBSERVATION)
    assert future['execution_ref'] is None
    assert future['preopen_input']['result'] == '392 只'
    assert nodes(future)['plan_19']['result'] is None
    assert {item['execution_status'] for item in nodes(future).values()} == {'NOT_DUE', 'DEFERRED_USER'}
    assert host.workflow()['observation_date'] is None
    assert nodes(host.workflow())['plan_1']['execution_status'] == 'CANNOT_CONFIRM_NO_RECEIPT'
    assert nodes(host.workflow('2026-10-29'))['plan_1']['execution_status'] == 'COMPLETED'


def test_preopen_input_does_not_hide_later_owner_receipts(tmp_path):
    original = pinned(tmp_path / 'owner.json', dict(status='COMPLETED'))
    legacy = pinned(tmp_path / 'legacy.json', dict(observation_date=OBSERVATION, nodes={
        '4': dict(status='COMPLETED', evidence=[original]),
    }))
    ref = pinned(tmp_path / 'projection.json', projection(preopen_input=dict(
        label='收盘数值候选', status='COMPLETED', recorded_at='2026-11-12T18:57:00+08:00', evidence=[original],
    )))
    view = host_fixture(tmp_path, workflow_node_evidence={OBSERVATION: ref}, workflow_execution=legacy).workflow(SOURCE)
    assert view['preopen_input']['status'] == 'COMPLETED'
    assert nodes(view)['plan_4']['execution_evidence'] == [original]


@pytest.mark.parametrize('invalid', ['date_pair', 'source_sha', 'recorded_day', 'future_time', 'no_evidence', 'unsafe_url'])
def test_rejects_stale_future_or_unverified_results(tmp_path, invalid):
    material = pinned(tmp_path / 'receipt.json', dict(result='source'))
    node = dict(status='COMPLETED', recorded_at='2026-11-13T18:57:00+08:00', evidence=[material])
    bundle = projection(nodes={'19': node})
    if invalid == 'date_pair':
        bundle['next_target_date'] = '2026-11-14'
    elif invalid == 'source_sha':
        Path(material['path']).write_text('{}')
    elif invalid == 'recorded_day':
        node['recorded_at'] = '2026-11-12T18:57:00+08:00'
    elif invalid == 'future_time':
        node['recorded_at'] = '2026-11-13T23:00:00+08:00'
    elif invalid == 'no_evidence':
        node['evidence'] = []
    else:
        node['materials'] = [dict(label='跳转', url='/api/v4/../v5/action')]
    ref = pinned(tmp_path / 'projection.json', bundle)
    rows = nodes(host_fixture(tmp_path, workflow_node_evidence={OBSERVATION: ref}).workflow(SOURCE))
    assert rows['plan_19']['execution_status'] == 'CANNOT_CONFIRM_BAD_RECEIPT'
    assert rows['plan_19']['execution_evidence'] == []
    assert rows['plan_3']['execution_status'] == 'DEFERRED_USER'


def test_bad_subevent_keeps_independent_verified_event(tmp_path):
    good = pinned(tmp_path / 'good.json', dict(result='A'))
    drifted = pinned(tmp_path / 'drifted.json', dict(result='HK'))
    Path(drifted['path']).write_text('{}')
    ref = pinned(tmp_path / 'projection.json', projection(nodes={'13': dict(status='PARTIAL', result='双市场阶段', events=[
        dict(label='A 股', status='FAILED', evidence=[good]),
        dict(label='港股', status='COMPLETED', evidence=[drifted]),
    ])}))
    row = nodes(host_fixture(tmp_path, workflow_node_evidence={OBSERVATION: ref}).workflow(SOURCE))['plan_13']
    assert row['execution_status'] == 'PARTIAL'
    assert row['result'] is None
    assert [event['status'] for event in row['events']] == ['FAILED', 'CANNOT_CONFIRM_BAD_RECEIPT']


@pytest.mark.parametrize('clock, waiting', [
    ('08:59:59', {'plan_11', 'plan_12', 'plan_16'}),
    ('09:00:00', {'plan_12', 'plan_16'}),
    ('09:20:00', {'plan_16'}),
    ('15:45:00', set()),
])
def test_market_windows_have_known_first_boundaries(tmp_path, clock, waiting):
    host = host_fixture(tmp_path)
    host._clock = lambda: datetime.fromisoformat(f'{OBSERVATION}T{clock}+08:00')
    rows = nodes(host.workflow(SOURCE))
    mixed_windows = {'plan_11', 'plan_12', 'plan_16'}
    assert {node for node in mixed_windows if rows[node]['execution_status'] == 'NOT_DUE'} == waiting
    assert rows['plan_5']['planned_start_local'] is None
    assert rows['plan_20']['planned_start_local'] is None


def test_versions_poll_stats_originals_without_reading_and_get_checks_each_sha_once(tmp_path, monkeypatch):
    original = pinned(tmp_path / 'large_original.json', dict(result='source'))
    ref = pinned(tmp_path / 'projection.json', projection(nodes={'17': dict(
        status='PARTIAL', evidence=[original],
        events=[dict(label='16:10 重试', status='PARTIAL', evidence=[original])],
    )}))
    owner = tmp_path / ('a-' + OBSERVATION.replace('-', '') + '.json')
    host = host_fixture(tmp_path, workflow_node_evidence={OBSERVATION: ref},
                        workflow_receipt_sources={'15': dict(kind='A_DAILY_PANEL_RECEIPT', root=str(tmp_path))})
    host.skill_r2 = None
    host._index = lambda: {}
    host._view = lambda *_: dict(manifest={}, source_generation='test', source_identity={'input_sha256': 'x'})
    host._v192_version = lambda _: {}
    host.classifications = SimpleNamespace(version=lambda: 'test')
    original_reads = []
    read_bytes = research_workbench_host.checked_bytes

    def record_read(ref):
        if ref['path'] == original['path']:
            original_reads.append(ref)
        return read_bytes(ref)

    monkeypatch.setattr(research_workbench_host, 'checked_bytes', record_read)
    before = host.versions(SOURCE)['modules']['workflow']
    assert host.versions(SOURCE)['modules']['workflow'] == before
    pinned(owner, dict(status='READY'))
    after_owner = host.versions(SOURCE)['modules']['workflow']
    assert after_owner != before
    owner.unlink()
    assert host.versions(SOURCE)['modules']['workflow'] == before
    assert original_reads == []
    assert nodes(host.workflow(SOURCE))['plan_17']['execution_status'] == 'PARTIAL'
    assert original_reads == [original]
    Path(original['path']).write_text('{}')
    assert host.versions(SOURCE)['modules']['workflow'] != before
    assert original_reads == [original]
    assert nodes(host.workflow(SOURCE))['plan_17']['execution_status'] == 'CANNOT_CONFIRM_BAD_RECEIPT'
