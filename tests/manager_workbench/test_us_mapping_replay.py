from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import subprocess
import sys

import pytest

from v4.manager_workbench import us_mapping_replay as r


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.canonical(value))
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': r.file_sha(path)}


@pytest.fixture
def case(tmp_path):
    state = tmp_path / 'frozen-store'
    context = {'market': 'HK_CONNECT', 'target_date': '20261013', 'phase': 'NEXT_DAY',
               'cutoff': '2026-10-13T04:20:00+08:00', 'trigger': 'SCHEDULED',
               'source_sessions': {'us': '20261012', 'hk_price': '20261012'},
               'rules_version': 'fixture', 'scope_refs': {'source_cutoff': '2026-10-12T20:15:00Z'}}
    batch = {'context': context, 'lane': 'US_MAPPING', 'records': [], 'evidence_refs': [],
             'coverage': {}, 'gaps': [], 'universe_ref': 'frozen', 'scope_description': 'fixture'}
    batch['input_sha256'] = r.input_batch_sha(batch)
    body = {'authority': 'ORIGINAL_OWNERS_ONLY', 'derivative': True, 'context': context, 'batches': [batch]}
    sha = r.digest(body)
    input_ref = write(state / 'input_snapshots' / (sha + '.json'), body)
    input_ref['batches'] = [{'lane': 'US_MAPPING', 'input_sha256': batch['input_sha256']}]
    cat = {'run_id': 'original1', 'input_sha256': 'a' * 64, 'product_sha256': 'b' * 64}
    snap = {**cat, 'context': context, 'changes': {'input_snapshot_sha256': sha},
            'lanes': [{'lane': 'US_MAPPING', 'state': 'PARTIAL', 'rows': [
                {'symbol': 'HK.00001', 'decision': 'OBSERVATION_ONLY'}]}], 'counts': {}}
    row = {**cat, 'target_date': '20261013', 'phase': 'NEXT_DAY',
           'catalog': write(state / 'catalog/20261013/NEXT_DAY/original1.json', cat),
           'snapshot': write(state / 'snapshots/original1.json', snap),
           'input_snapshot_sha256': sha, 'exact_saved_input_replayable': True,
           'classification': 'RETROSPECTIVE_ONLY', 'pit_evidence_complete': False,
           'us_batch_input_sha256': batch['input_sha256'],
           'effective_proof_cutoff': r.temporal_cutoff(context), 'missing_evidence': ['PIT_PRICE_UNKNOWN']}
    sessions = [(date(2026, 7, 30) + timedelta(days=i)).strftime('%Y%m%d') for i in range(60)]
    inventory = {'schema': 'v4.us_hk.replay_inventory.v1', 'outcome_free': True,
                 'state_root': str(state), 'calendar': {'sessions': sessions},
                 'split': {'eligible_dates': [], 'sealed_dates': []}, 'runs': [row],
                 'inputs': {sha: input_ref}, 'days': [{'date': '20261013', 'saved_run_ids': ['original1']}]}
    freeze = {'code': {'engine_and_replay': {'engine': 'a'}, 'preopen_projection': {'pure': 'b'}},
              'python': 'fixture', 'metric_policy': {}, 'split': {}, 'inventory_sha256': r.digest(inventory),
              'freeze_sha256': 'f' * 64,
              'safety': {'RESEARCH_ONLY': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}}
    return inventory, row, freeze


def selected_payload(decision='PENDING'):
    return {'selection': {'schema_version': 'v4.us_hk.selection.v1',
            'candidates': [{'symbol': 'HK.00001', 'research_state': 'pending', 'paths': []}],
            'strict_decisions': [{'symbol': 'HK.00001', 'decision': decision, 'gates': []}],
            'counts': {'selected': int(decision == 'SELECTED'), 'pending': 1}}}


def test_frozen_loader_keeps_original_clocks_and_batch(case):
    inventory, row, _ = case
    context, batch, before = r.load_case(inventory, row)
    assert context == batch['context']
    assert context['cutoff'] == '2026-10-13T04:20:00+08:00'
    assert context['scope_refs']['source_cutoff'] == '2026-10-12T20:15:00Z'
    assert r.temporal_cutoff(context) == '2026-10-12T20:15:00+00:00'
    assert before['symbols'] == {'HK.00001': ['OBSERVATION_ONLY']}


def test_source_cutoff_unknown_is_not_execution_time(case):
    inventory, _, _ = case
    context = json.loads(Path(next(iter(inventory['inputs'].values()))['path']).read_text())['context']
    context['scope_refs'].clear()
    assert r.temporal_cutoff(context) is None


def test_final_reject_with_pending_gate_is_not_complete_cash_zero():
    selection = selected_payload()['selection']
    selection['evaluation_complete'] = True
    selection['strict_decisions'][0].update(decision='REJECTED', state='REJECT', gates=[
        {'gate': 'relation', 'state': 'REJECT'}, {'gate': 'price', 'state': 'PENDING'}])
    status = r.completeness(selection)
    assert status['evaluation_complete'] is False
    assert status['pending_gate_count'] == 1
    assert status['daily_return'] is None


@pytest.mark.parametrize('flag', [None, False, True])
def test_empty_result_needs_explicit_completeness_and_pit_still_unverified(flag):
    selection = {'strict_decisions': []}
    if flag is not None:
        selection['evaluation_complete'] = flag
    status = r.completeness(selection)
    assert status['evaluation_complete'] is (flag is True)
    assert status['daily_return'] is None
    assert status['effect_status'] == 'NOT_EVALUABLE'


def test_stock_sets_and_top10_keep_full_candidate_order():
    selection = {'candidates': [{'symbol': f'HK.{i:05}', 'research_state': 'pending'} for i in range(12)],
                 'strict_decisions': [{'symbol': f'HK.{i:05}', 'decision': 'PENDING'} for i in range(12)]}
    diff = r.selection_diff({'symbols': {'HK.99999': ['OBSERVATION_ONLY']}}, selection)
    assert len(diff['after_candidate_symbols']) == 12
    assert diff['candidate_original_order_top10'] == [f'HK.{i:05}' for i in range(10)]
    assert diff['removed_symbols'] == ['HK.99999']
    assert len(diff['stock_fates']) == 13


def test_corrupted_file_and_path_escape_rejected(case, tmp_path):
    inventory, row, _ = case
    ref = inventory['inputs'][row['input_snapshot_sha256']]
    Path(ref['path']).write_text('{}')
    with pytest.raises(r.ReplayError, match='FROZEN_FILE_SHA_MISMATCH'):
        r.load_case(inventory, row)
    outside = write(tmp_path / 'outside.json', {})
    with pytest.raises(r.ReplayError, match='UNSAFE_FROZEN_PATH'):
        r.read_verified(outside, inventory['state_root'])
    with pytest.raises(r.ReplayError, match='UNSAFE_FROZEN_PATH'):
        r.read_verified({**outside, 'path': str(Path(inventory['state_root']) / '..' / 'outside.json')}, inventory['state_root'])


def test_input_body_or_batch_context_mismatch_not_normalized_away(case):
    inventory, row, _ = case
    ref = inventory['inputs'][row['input_snapshot_sha256']]
    body = json.loads(Path(ref['path']).read_text())
    body['batches'][0]['context'] = deepcopy(body['context'])
    body['batches'][0]['context']['cutoff'] = '2026-10-13T05:00:00+08:00'
    # Clock is deliberately excluded from batch source identity; body and context
    # binding must still reject this change, even with a correctly rehashed body.
    new_sha = r.digest(body)
    new_ref = write(Path(inventory['state_root']) / 'input_snapshots' / (new_sha + '.json'), body)
    new_ref['batches'] = ref['batches']
    inventory['inputs'][new_sha] = new_ref
    row['input_snapshot_sha256'] = new_sha
    with pytest.raises(r.ReplayError, match='INPUT_CONTEXT_MISMATCH'):
        r.load_case(inventory, row)


def test_actual_callable_contract_is_deterministic_with_unmodified_context(case):
    inventory, row, freeze = case
    seen = []
    def engine(context, batch):
        seen.append((deepcopy(context), batch['input_sha256']))
        return selected_payload()
    value = r.execute_case(inventory, row, freeze, engine=engine, deterministic=True)
    assert value['status'] == 'REPLAYED_ENGINEERING_ONLY'
    assert len(seen) == 2 and seen[0] == seen[1]
    assert value['comparison']['stock_fates'][0]['after_decision'] == 'PENDING'
    assert value['effect_status'] == 'NOT_EVALUABLE' and not value['pit_evaluable']


def test_mutation_or_selected_without_historical_proof_is_failure(case):
    inventory, row, freeze = case
    def mutate(context, batch):
        batch['records'].append({'changed': True})
        return selected_payload()
    result = r.execute_case(inventory, row, freeze, engine=mutate)
    assert result['status'] == 'RUNTIME_FAILURE'
    assert result['error']['message'] == 'ENGINE_MUTATED_FROZEN_BATCH'
    result = r.execute_case(inventory, row, freeze, engine=lambda c, b: selected_payload('SELECTED'))
    assert result['status'] == 'RUNTIME_FAILURE'
    assert result['error']['message'] == 'SELECTED_WITHOUT_FROZEN_HISTORICAL_PRICE_PROOF'


def test_nonconstant_engine_semantics_fail_determinism(case):
    inventory, row, freeze = case
    calls = []
    def engine(c, b):
        value = selected_payload()
        value['selection']['gaps'] = [str(len(calls))]
        calls.append(True)
        return value
    result = r.execute_case(inventory, row, freeze, engine=engine, deterministic=True)
    assert result['error']['message'] == 'SAME_INPUT_SEMANTICS_DIFFER'


def test_preopen_uses_delegated_projection_and_original_source_input(case):
    inventory, direct, freeze = case
    source_sha = direct['input_snapshot_sha256']
    context, batch, _ = r.load_case(inventory, direct)
    frozen = {**context, 'phase': 'PREOPEN', 'cutoff': '2026-10-13T09:25:00+08:00'}
    row = deepcopy(direct)
    row.update(run_id='preopen1', phase='PREOPEN', input_snapshot_sha256=None,
        source_input_snapshot_sha256=source_sha, exact_saved_input_replayable=False,
        source_linked_us_input_replayable=True, snapshot_context=frozen,
        freeze_context={'source_run_id': 'original1'})
    snap = {'run_id': 'preopen1', 'product_sha256': row['product_sha256'], 'context': frozen,
            'changes': {'source_run_id': 'original1'}, 'lanes': [{'lane': 'US_MAPPING',
             'state': 'PARTIAL', 'input_sha256': batch['input_sha256'], 'rows': []}]}
    row['snapshot'] = write(Path(inventory['state_root']) / 'snapshots/preopen1.json', snap)
    row['catalog'] = write(Path(inventory['state_root']) / 'catalog/20261013/PREOPEN/preopen1.json',
                           {k: row[k] for k in ('run_id', 'input_sha256', 'product_sha256')})
    inventory['runs'].append(row)
    seen = []
    def engine(c, b):
        assert c['phase'] == 'NEXT_DAY'
        assert c['cutoff'] == context['cutoff']
        return selected_payload()
    def project(lane, *, cutoff):
        seen.append(cutoff)
        return lane
    result = r.execute_case(inventory, row, freeze, engine=engine, preopen=project)
    assert result['status'] == 'REPLAYED_ENGINEERING_ONLY'
    assert seen == [frozen['cutoff']]
    assert result['original_context']['cutoff'] == context['cutoff']


def test_missing_run_and_aggregate_never_turn_into_cash(case):
    inventory, row, freeze = case
    row['exact_saved_input_replayable'] = False
    row['classification'] = 'MISSING_REPLAY_INPUT'
    value = r.execute_case(inventory, row, freeze, engine=lambda c, b: pytest.fail('must not call'))
    assert value['status'] == 'MISSING_REPLAY_INPUT'
    aggregate = r.aggregate(inventory, freeze, [])
    assert aggregate['coverage_denominator'] == 60
    assert aggregate['days'][0]['daily_return'] is None
    assert aggregate['curve_segments'] == []


def test_output_and_checkpoint_are_immutable_and_content_bound(case, tmp_path, monkeypatch):
    inventory, row, freeze = case
    root = tmp_path / 'derived'
    value = r.execute_case(inventory, row, freeze, engine=lambda c, b: selected_payload())
    value['receipt_sha256'] = r.digest(value)
    path = root / 'cases' / row['target_date'] / (row['run_id'] + '-' + r.case_fingerprint(freeze, row) + '.json')
    r.atomic_json(path, value)
    reused = r.run_to_checkpoint(inventory, row, freeze, root)
    assert reused['reused']
    with pytest.raises(r.ReplayError, match='IMMUTABLE_REPLAY_OUTPUT_COLLISION'):
        r.atomic_json(path, {'different': True})
    changed = deepcopy(freeze); changed['code']['engine_and_replay']['engine'] = 'changed'
    assert r.case_fingerprint(changed, row) != value['fingerprint']
    changed = deepcopy(freeze); changed['code']['preopen_projection']['pure'] = 'changed'
    assert r.case_fingerprint(changed, row) == value['fingerprint']
    Path(inventory['inputs'][row['input_snapshot_sha256']]['path']).write_text('{}')
    with pytest.raises(r.ReplayError, match='FROZEN_FILE_SHA_MISMATCH'):
        r.run_to_checkpoint(inventory, row, freeze, root)


def test_inventory_hash_and_zero_eligible_gate(case, tmp_path):
    inventory, _, _ = case
    path = tmp_path / 'inventory.json'
    write(path, inventory)
    assert r.load_inventory(path, r.file_sha(path))['outcome_free']
    with pytest.raises(r.ReplayError, match='INVENTORY_SHA_MISMATCH'):
        r.load_inventory(path, '0' * 64)
    inventory['split']['eligible_dates'] = [inventory['calendar']['sessions'][0]]
    write(path, inventory)
    with pytest.raises(r.ReplayError, match='FROZEN_INVENTORY_CONTRACT_INVALID'):
        r.load_inventory(path, r.file_sha(path))
    with pytest.raises(r.ReplayError, match='OUTPUT_NOT_ISOLATED'):
        r.output_root(tmp_path.parent, path)


def test_cli_runtime_guard_denies_network_process_and_external_writes(tmp_path):
    root = tmp_path / 'derived'; root.mkdir()
    outside = tmp_path / 'must-not-exist'
    code = '''
import sys, socket, subprocess
from pathlib import Path
from ops.replay_us_mapping_selection import install_read_only_guard, ReplayError
root, outside = Path(sys.argv[1]), Path(sys.argv[2])
install_read_only_guard(root)
(root / 'allowed').write_text('ok')
for action in [lambda: outside.write_text('bad'), lambda: socket.socket(), lambda: subprocess.run(['true'])]:
    try:
        action()
    except ReplayError:
        pass
    else:
        raise AssertionError('guard did not deny action')
assert not outside.exists()
'''
    completed = subprocess.run([sys.executable, '-B', '-c', code, str(root), str(outside)],
                               cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert not outside.exists()
