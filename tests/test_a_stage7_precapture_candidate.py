from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
import sys
from types import SimpleNamespace

import pytest

from stage_center import a_stage7_precapture as stage7
from stage_center.acquisition import AcquisitionPlan, SourceResult


DATE = '20261116'
SHA = 'f' * 64


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    candidate = tmp_path / 'inputs'
    candidate.mkdir()
    output = tmp_path / 'v4-stage7-candidate.test'
    output.mkdir(mode=0o700)
    frozen = SimpleNamespace(root=candidate, codes=('A.600000',), run_id='pinned',
                             current_sha256=SHA, artifact_sha256='a' * 64)
    plan = AcquisitionPlan(DATE, stage7.STAGE_ID, ('A_SHARE', 'HK_CONNECT'), frozen, 'hq', 'hk')
    monkeypatch.setattr(stage7, 'build_plan', lambda *_args, **_kwargs: plan)
    return candidate, output, frozen


def capture_inputs(inputs, *, end='14:58:03', update='14:58:00', code='SH.600000', safe=True,
                   started='14:57:55', stdout='provider response'):
    candidate, output, _ = inputs
    instants = iter([started, '14:57:56', end, end, end])

    def clock():
        return datetime.fromisoformat(f'2026-11-16T{next(instants)}+08:00')

    def process(command, **kwargs):
        assert kwargs['timeout'] <= 124
        assert kwargs['env']['PYTHONDONTWRITEBYTECODE'] == '1'
        return CompletedProcess(command, 0, stdout, '')

    def collector(plan, *, codes, python_path, shared_root, process_runner):
        assert plan.markets == ('A_SHARE',) and codes == ('A.600000',)
        assert sys.dont_write_bytecode
        process_runner(['fixture'], input=json.dumps(dict(trade_date=DATE, stage_id=stage7.STAGE_ID,
                                                         codes=['SH.600000'])), timeout=180)
        row = dict(
            batch_index=1, code=code, name='fixture', update_time=f'2026-11-16 {update}', last_price=1,
            open_price=1, high_price=1, low_price=1, prev_close_price=1, turnover=1, volume=1,
            bid_price='', ask_price='', bid_vol='', ask_vol='', window_start='2026-11-16 14:46:00',
            window_end=f'2026-11-16 {update}', bar_count=1, temporal_cutoff_safe=safe,
        )
        return SourceResult('pytdx_hq', 'READY', rows=(row,), requested_rows=1)

    return clock, process, collector


def fixture_capture(inputs, **fields):
    candidate, output, _ = inputs
    clock, process, collector = capture_inputs(inputs, **fields)
    return stage7.capture(candidate, DATE, SHA, output_root=output, shared_root=candidate,
                          _clock=clock, _process_runner=process, _collector=collector)


def test_a_only_fixture_keeps_hash_bound_evidence_without_raw_pointer(inputs):
    candidate, output, _ = inputs
    dry = stage7.dry_run(candidate, DATE, SHA)
    assert dry['market'] == 'A_SHARE' and dry['requested_rows'] == 1 and not dry['provider_called']
    receipt = fixture_capture(inputs)
    assert receipt['status'] == 'FIXTURE_PRE_CUTOFF' and receipt['accepted_rows'] == 1
    assert receipt['fixture'] and receipt['RESEARCH_ONLY']
    assert not receipt['temporal_cutoff_safe'] and not receipt['natural_verified'] and not receipt['formal_pool_ready']
    assert receipt['raw'] is None and not list(output.rglob('latest.json'))
    ref = receipt['receipt']
    assert sha256(Path(ref['path']).read_bytes()).hexdigest() == ref['sha256']
    process, = receipt['processes']
    assert sha256(Path(process['stdout_path']).read_bytes()).hexdigest() == process['stdout_sha256']


@pytest.mark.parametrize('fields,reason', [
    ({'end': '15:00:00'}, 'STAGE7_CAPTURE_PROVIDER_WINDOW_UNVERIFIED'),
    ({'update': '14:58:04'}, 'STAGE7_CAPTURE_ROW_ASOF_OR_MEMBERSHIP_INVALID'),
    ({'code': 'HK.00700'}, 'invalid A_SHARE code'),
    ({'safe': False}, 'temporal_cutoff_safe must be true'),
])
def test_rejects_cutoff_overrun_future_bar_other_market_and_unsafe_row(inputs, fields, reason):
    receipt = fixture_capture(inputs, **fields)
    assert receipt['status'] == 'CANNOT_CONFIRM'
    assert reason in receipt['cannot_confirm'][0]
    assert receipt['raw'] is None and receipt['accepted_rows'] == 0


def test_refuses_clock_outside_window_and_owner_output_root(inputs):
    candidate, output, _ = inputs
    receipt = stage7.capture(
        candidate, DATE, SHA, output_root=output, shared_root=candidate,
        _clock=lambda: datetime.fromisoformat('2026-11-14T14:57:00+08:00'),
        _process_runner=lambda *a, **kw: pytest.fail('provider called outside exact wall date'),
    )
    assert not receipt['provider_called']
    assert receipt['cannot_confirm'] == ['STAGE7_CAPTURE_WALL_TIME_OUTSIDE_WINDOW']
    (output / 'latest.json').symlink_to(output / 'nonexistent')
    with pytest.raises(ValueError, match='STAGE7_CAPTURE_OUTPUT_IS_OWNER_STORE'):
        fixture_capture(inputs)
    with pytest.raises(ValueError, match='STAGE7_CAPTURE_OUTPUT_OVERLAPS_CANDIDATE_INPUT'):
        stage7.capture(candidate, DATE, SHA, output_root=candidate, shared_root=candidate)


def test_refuses_wrong_market_input_before_collector(inputs):
    candidate, _, frozen = inputs
    frozen.codes = ('HK.00700',)
    with pytest.raises(ValueError, match='STAGE7_CAPTURE_CANDIDATE_MARKET_INVALID'):
        stage7.dry_run(candidate, DATE, SHA)


@pytest.mark.parametrize('timeout, failure_type', [(True, 'CUTOFF_BUDGET_TIMEOUT'), (False, 'PROVIDER_NONZERO_EXIT')])
def test_keeps_sanitized_process_failure_evidence(inputs, timeout, failure_type):
    candidate, output, _ = inputs
    clock, _, _ = capture_inputs(inputs)
    stderr = b'x' * 5000 + b'secret'

    def process(command, **kwargs):
        if timeout:
            raise TimeoutExpired(command, kwargs['timeout'], stderr=stderr)
        return CompletedProcess(command, 7, 'noisy error output', stderr)

    def collector(plan, *, codes, python_path, shared_root, process_runner):
        try:
            process_runner(['fixture'], input=json.dumps(dict(trade_date=DATE, stage_id=stage7.STAGE_ID,
                                                             codes=['SH.600000'])), timeout=180)
        except TimeoutExpired:
            pass
        return SourceResult('pytdx_hq', 'CANNOT_CONFIRM', requested_rows=1)

    receipt = stage7.capture(candidate, DATE, SHA, output_root=output, shared_root=candidate,
                             _clock=clock, _process_runner=process, _collector=collector)
    assert receipt['status'] == 'CANNOT_CONFIRM'
    assert failure_type in receipt['cannot_confirm'][0]
    batch, = receipt['processes']
    assert batch['returncode'] == (None if timeout else 7)
    assert batch['failure_type'] == failure_type
    assert batch['stderr_bytes'] == len(stderr)
    assert batch['stderr_tail_bytes'] == 4096
    assert batch['stderr_tail_sha256'] == sha256(stderr[-4096:]).hexdigest()
    assert b'secret' not in Path(receipt['receipt']['path']).read_bytes()
    assert Path(batch['stdout_path']).read_bytes() == b''


@pytest.mark.parametrize('name', ['receipts', 'selection'])
def test_refuses_marker_free_configured_owner_output(inputs, name):
    candidate, output, _ = inputs
    owner_root = output.parent / 'configured-stage-root' / name
    owner_root.mkdir(parents=True, mode=0o700)
    with pytest.raises(ValueError, match='STAGE7_CAPTURE_FRESH_PRIVATE_SCRATCH_REQUIRED'):
        stage7.capture(candidate, DATE, SHA, output_root=owner_root, shared_root=candidate)


@pytest.mark.parametrize('time_key', ['2026-11-16 14:58:00', None])
def test_live_branch_quarantines_owner_ordinal_time_and_rejects_unstamped_output(inputs, monkeypatch, time_key):
    candidate, output, _ = inputs
    module = candidate / 'scripts/live_acquisition/pytdx_hq.py'
    module.parent.mkdir(parents=True)
    module.write_bytes(b'fixture owner')
    stdout = stage7.HQ_MARKER + json.dumps(dict(raw_rows=[dict(time_key=time_key)]))
    clock, process, collector = capture_inputs(inputs, stdout=stdout)
    monkeypatch.setattr(stage7, 'VERIFIED_HQ_MODULE_SHA256', sha256(module.read_bytes()).hexdigest())
    monkeypatch.setattr(stage7, '_now', clock)
    monkeypatch.setattr(stage7, 'SYSTEM_SCRATCH_ROOT', output.parent)
    monkeypatch.setattr(stage7, 'collect_a_share_hq_minute', collector)
    monkeypatch.setattr(stage7.subprocess, 'run', process)
    receipt = stage7.capture(candidate, DATE, SHA, output_root=output, shared_root=candidate)
    if time_key is None:
        assert receipt['status'] == 'CANNOT_CONFIRM'
        assert receipt['cannot_confirm'] == ['STAGE7_CAPTURE_HQ_OWNER_TIME_KEY_MISSING']
        assert receipt['raw'] is None
        return
    assert receipt['status'] == 'CANDIDATE_PRE_CUTOFF'
    assert receipt['captured_before_cutoff'] is True
    assert receipt['raw']['status'] == 'PARTIAL_WITH_ROWS'
    assert receipt['cannot_confirm'] == [stage7.TIME_LIMITATION]
    assert receipt['provider_native_timestamp_verified'] is False
    assert receipt['temporal_cutoff_safe'] is False
