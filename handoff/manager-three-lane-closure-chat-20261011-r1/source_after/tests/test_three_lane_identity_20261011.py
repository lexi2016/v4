"""Owner-contract identity regressions; fixtures are synthetic, never live inputs."""
from copy import deepcopy
import pytest

from v4.manager_research.evidence_identity import merge_event_rows
from v4.manager_research.workspace_identity import semantic_digest, semantic_value
from v4.manager_research.research_attention import build_research_attention


def _binding(slot, manifest):
    return dict(source_id='V35_RESEARCH_DATA_ROOT', source_root='/synthetic/research',
        ledger_root='/synthetic/dispatcher', binding_policy='EXPLICIT_RESEARCH_DATA_ROOT_OR_SERVER_DATA_ROOT',
        status='VERIFIED', source_date='20261009', slot=slot, mode='LIVE',
        payload_path=f'research/hourly/live/20261009/{slot}.json',
        receipt_path=f'receipts/research/hourly/live/20261009/{slot}.json',
        payload_sha256='a' * 64, receipt_sha256='b' * 64,
        manifest_path='manifest.json', manifest_sha256=manifest * 64,
        write_policy='read_only', recommendation_status='RESEARCH_ONLY',
        production_allowed=False, buy_gate_updated=False, orders_sent=False)


def _merged(manifests):
    rows = [dict(source_url='https://example.invalid/synthetic',
        title='Synthetic same owner event', published_at='2026-10-09T08:00:00+08:00',
        available_at='2026-10-09T08:01:00+08:00',
        source_refs=[_binding(f'{9+i:02d}00', manifest)])
        for i, manifest in enumerate(manifests)]
    return merge_event_rows('HK.00001', rows)


def test_original_merge_ref_order_cannot_turn_manifest_churn_into_input_change():
    before, after = _merged(['d', 'c']), _merged(['d', 'd'])
    frozen = deepcopy(before)
    assert [ref['slot'] for ref in before[0]['source_refs']] != [ref['slot'] for ref in after[0]['source_refs']]
    assert semantic_digest(before) == semantic_digest(after)
    assert before == frozen  # Raw original provenance remains available for audit.


def test_uniform_registry_refs_preserve_legacy_canonical_semantic_order():
    merged = _merged(['d'] * 6)
    original_slots = [ref['slot'] for ref in merged[0]['source_refs']]
    normalized_slots = [ref['slot'] for ref in semantic_value(merged)[0]['source_refs']]
    assert normalized_slots == original_slots


@pytest.mark.parametrize('key,value', [
    ('payload_sha256', 'e' * 64), ('receipt_sha256', 'f' * 64),
    ('payload_path', 'research/hourly/live/20261009/0930.json'),
    ('receipt_path', 'receipts/research/hourly/live/20261009/0930.json'),
    ('source_date', '20261008'), ('source_root', '/different/research'),
    ('available_at', '2026-10-09T08:02:00+08:00'), ('production_allowed', True),
])
def test_relevant_binding_changes_remain_semantic(key, value):
    before = {'source_refs': [_binding('0900', 'c'), _binding('1000', 'd')]}
    after = deepcopy(before)
    after['source_refs'][0][key] = value
    assert semantic_digest(before) != semantic_digest(after)


def test_normalization_keeps_unknown_arrays_content_and_reference_multiplicity():
    ref = _binding('0900', 'c')
    for key in ('source_row', 'original_source_row', 'content', 'unknown_list'):
        before, after = {key: [ref]}, {key: [dict(ref, manifest_sha256='d' * 64)]}
        assert semantic_digest(before) != semantic_digest(after)
    assert semantic_digest({'source_refs': [ref]}) != semantic_digest({'source_refs': [ref, ref]})
    bad = dict(ref, source_id='UNKNOWN_OWNER')
    assert semantic_value({'source_refs': [bad, ref]})['source_refs'][0]['manifest_sha256'] == 'c' * 64


def _peripheral(manifest):
    return dict(owner='ResearchPeripheralStore', source='external_finance', session_date='20261008',
        status='VERIFIED', payload_path='research/peripherals/20261008/external_finance.json',
        receipt_path='receipts/research/peripherals/20261008/external_finance.json',
        manifest_path='research/peripherals/manifest.json', payload_sha256='a' * 64,
        receipt_sha256='b' * 64, manifest_sha256=manifest * 64)


def _attention(lineage):
    return build_research_attention('20261009',
        context=dict(research_cutoff='2026-10-09T09:29:00+08:00', focus_window_start='2026-10-08T16:00:00+08:00'),
        market_screen=None, stocks=[], material_cards=[], themes=[],
        announcement_observation=None,
        us_market=dict(status='PARTIAL', source_identity=lineage, gaps=[]))


def test_original_peripheral_manifest_is_provenance_not_attention_input():
    before, after = _attention(_peripheral('c')), _attention(_peripheral('d'))
    assert before['cards'] == after['cards']
    assert before['research_selection'] == after['research_selection']
    assert before['input_identity'] == after['input_identity']


@pytest.mark.parametrize('key,value', [
    ('payload_sha256', 'e' * 64), ('receipt_sha256', 'e' * 64),
    ('session_date', '20261007'), ('payload_path', 'wrong.json'),
    ('receipt_path', 'wrong.json'), ('manifest_path', 'other/manifest.json'),
    ('owner', 'OTHER_OWNER'), ('status', 'CANNOT_CONFIRM'),
])
def test_peripheral_payload_and_incomplete_contract_are_not_normalized_away(key, value):
    original = _peripheral('c')
    changed = dict(original, **{key: value})
    assert _attention(original)['input_identity'] != _attention(changed)['input_identity']
    if key in {'owner', 'status', 'manifest_path'}:
        assert semantic_digest({'us_source_identity': changed}) != semantic_digest(
            {'us_source_identity': dict(changed, manifest_sha256='d' * 64)})


def test_cutoff_dates_and_raw_source_content_remain_identity_inputs():
    value = dict(source_refs=[_binding('0900', 'c')], cutoff='2026-10-09T09:29:00+08:00', target_date='20261009')
    assert semantic_digest(value) != semantic_digest(dict(value, target_date='20261012'))
    assert semantic_digest(value) != semantic_digest(dict(value, cutoff='2026-10-09T09:30:00+08:00'))
    assert semantic_digest({'source_row': _peripheral('c')}) != semantic_digest({'source_row': _peripheral('d')})
