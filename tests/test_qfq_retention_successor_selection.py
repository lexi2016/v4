import copy
import hashlib
import json
import struct
from datetime import date, timedelta
from pathlib import Path

import pytest
from ops import research_panel_qfq as q


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def selection(tmp_path, monkeypatch):
    names = ('V4_QFQ_RETENTION_BASELINE_PATH', 'V4_QFQ_RETENTION_BASELINE_SHA256',
             'V4_QFQ_RETENTION_SUCCESSOR_PATH', 'V4_QFQ_RETENTION_SUCCESSOR_SHA256')
    for name in names:
        monkeypatch.delenv(name, raising=False)
    day = date(2023, 3, 28)
    dates = []
    while len(dates) < 867:
        if day.weekday() < 5:
            dates.append(int(day.strftime('%Y%m%d')))
        day += timedelta(days=1)
    dates.append(20261110)
    raw = b''.join(struct.pack('<I28s', day, b'x' * 28) for day in dates)
    source = write(tmp_path / 'source.day', raw)
    whole = write(tmp_path / 'whole.day', raw)
    events = [dict(ex_date=d, a=1., b=-.1, volume_a=1.) for d in (20230526, 20240529, 20250528, 20260527)]
    response = write(tmp_path / 'events.json', {'rows': [dict(ex_div_date=f"{r['ex_date']//10000:04}-{r['ex_date']//100%100:02}-{r['ex_date']%100:02}", forward_adj_factorA=r['a'], forward_adj_factorB=r['b'], backward_adj_factorA=r['volume_a']) for r in events]})
    fact = write(tmp_path / 'fact.json', dict(schema='V4_EXACT_301314_20261110_TYPED_SOURCE_FACT_V1', symbol='301314.SZ', target_date=20261110, resolved_rows=868, raw_refs=[source], events=events, factor_response=response))
    review = write(tmp_path / 'review.json', dict(verdict='REVIEWED/PASS', reviewer='independent', source_fact_sha256=fact['sha256']))
    relocation = write(tmp_path / 'relocation.json', dict(original_ref=source, frozen_copy=whole))
    before = dict(source_resolution='existing', stocks=[dict(code=f'{i:06}.SZ', sources=[]) for i in range(5541)])
    oldcfg = write(tmp_path / 'before.json', before)
    after = copy.deepcopy(before)
    after['stocks'].append(dict(code='301314.SZ', sources=[dict(name='native', kind='day_bytes', **whole)]))
    newcfg = write(tmp_path / 'after.json', after)
    old = dict(source_config=oldcfg, source_policy={'existing': 'policy'}, archive_refs=[], accepted_evidence=[])
    new = dict(old, source_config=newcfg, accepted_evidence=[fact, review, relocation])
    oldref = write(tmp_path / 'baseline.json', old)
    newref = write(tmp_path / 'successor.json', new)
    def bind(value=None):
        nonlocal newref
        if value is not None:
            newref = write(tmp_path / 'successor.json', value)
        for name, value in zip(names, (oldref['path'], oldref['sha256'], newref['path'], newref['sha256'])):
            monkeypatch.setenv(name, value)
    return dict(old=old, new=new, before=before, after=after, fact=fact, review=review, bind=bind, root=tmp_path)


def test_default_has_no_new_io_or_behavior(selection):
    assert q.selected_history_retention(selection['old'], target=20261111) is selection['old']


def test_selects_once_and_is_idempotent_with_successor_footer(selection):
    selection['bind']()
    assert q.selected_history_retention(selection['old'], target=20261110) == selection['new']
    assert q.selected_history_retention(selection['new'], target=20261110) == selection['new']


def test_next_session_revalidates_frozen_material_without_requiring_old_live_sha(selection):
    selection['bind']()
    assert q.selected_history_retention(selection['old'], target=20261110) == selection['new']
    live = selection['root'] / 'source.day'
    live.write_bytes(live.read_bytes() + struct.pack('<I28s', 20261111, b'y' * 28))
    assert q.selected_history_retention(selection['new'], target=20261111) == selection['new']
    # First admission still requires the exact original source, even on D10.
    with pytest.raises(q.QfqGateError):
        q.selected_history_retention(selection['old'], target=20261110)


@pytest.mark.parametrize('kind', ['partial', 'sha', 'date', 'moved', 'member', 'other_key', 'code', 'policy', 'review', 'raw', 'events'])
def test_selection_fails_closed(selection, monkeypatch, kind):
    s = selection
    new = copy.deepcopy(s['new'])
    if kind in ('member', 'other_key', 'code', 'raw'):
        after = copy.deepcopy(s['after'])
        if kind == 'member': after['stocks'][0]['code'] = 'BAD'
        if kind == 'other_key': after['source_resolution'] = 'changed'
        if kind == 'code': after['stocks'][-1]['code'] = '301315.SZ'
        if kind == 'raw': after['stocks'][-1]['sources'][0].update(write(s['root'] / 'bad.day', b'0' * (868 * 32)))
        new['source_config'] = write(s['root'] / 'mutated.json', after)
    if kind == 'policy': new['source_policy'] = {'changed': True}
    if kind == 'review': new['accepted_evidence'] = [s['fact']]
    if kind == 'events':
        eventref = json.loads(Path(s['fact']['path']).read_text())['factor_response']
        Path(eventref['path']).write_text('{}')
    s['bind'](new)
    if kind == 'partial': monkeypatch.delenv('V4_QFQ_RETENTION_SUCCESSOR_SHA256')
    if kind == 'sha': monkeypatch.setenv('V4_QFQ_RETENTION_SUCCESSOR_SHA256', '0' * 64)
    with pytest.raises(q.QfqGateError):
        q.selected_history_retention({'changed': True} if kind == 'moved' else s['old'], target=20261111 if kind == 'date' else 20261110)


@pytest.mark.parametrize('missing_sha', [True, False])
def test_explicit_acceptance_requires_correct_sha_before_oracle(tmp_path, monkeypatch, missing_sha):
    p = write(tmp_path / 'acceptance.json', {})
    monkeypatch.setenv('V4_QFQ_CONVENTION_ACCEPTANCE_PATH', p['path'])
    if missing_sha:
        monkeypatch.delenv('V4_QFQ_CONVENTION_ACCEPTANCE_SHA256', raising=False)
    else:
        monkeypatch.setenv('V4_QFQ_CONVENTION_ACCEPTANCE_SHA256', '0' * 64)
    with pytest.raises(q.QfqGateError):
        q.verify_release_gate(tmp_path, tmp_path / 'unused.parquet', {}, 20261110, 'original')


def test_explicit_acceptance_uses_original_tuple_and_initial_oracle_gate(tmp_path, monkeypatch):
    identity = {key: 'a' * 64 for key in ('driver_sha256', 'formula_sha256', 'adapter_sha256',
                'input_adapter_sha256', 'factor_cache_sha256', 'tdx_adapter_sha256',
                'user_formula_sha256', 'field_contract_sha256')}
    oracle = write(tmp_path / 'original_oracle_receipt.json', dict(status='PASS_FUTU_DISPLAY_ORACLE', asof_date=20261029, code_binding=identity))
    accepted = write(tmp_path / 'release_acceptance.json', dict(status='PASS', reviewer_id='independent', code_binding=identity, convention='original', initial_asof_date=20261029, initial_oracle_receipt=oracle))
    monkeypatch.setenv('V4_QFQ_CONVENTION_ACCEPTANCE_PATH', accepted['path'])
    monkeypatch.setenv('V4_QFQ_CONVENTION_ACCEPTANCE_SHA256', accepted['sha256'])
    q.verify_release_gate(tmp_path, tmp_path / 'unused.parquet', identity, 20261110, 'original')
    monkeypatch.delenv('V4_QFQ_CONVENTION_ACCEPTANCE_PATH')
    monkeypatch.delenv('V4_QFQ_CONVENTION_ACCEPTANCE_SHA256')
    with pytest.raises(q.QfqGateError, match='CONVENTION_NOT_ACCEPTED'):
        q.verify_release_gate(tmp_path, tmp_path / 'unused.parquet', identity, 20261110, 'original')
