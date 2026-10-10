from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

PROCESS_ROOT = Path('/Users/lexi/Desktop/学习/agents调试/V4_SELECTION_REUSE_REPAIR_MAC_20261010_R1')
APP_ROOT = PROCESS_ROOT / 'ledger-contract-r5' / 'candidate' / 'app'
FIXTURE = PROCESS_ROOT / 'evidence' / 'final-workspace-readback-1.json'
sys.path.insert(0, str(APP_ROOT))

from v4.manager_research.research_attention import build_research_selection_ledger


@pytest.fixture(scope='module')
def readback() -> dict:
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def _ledger(screen: dict, attention: dict) -> dict:
    return build_research_selection_ledger(screen, attention['cards'], '20261009')


def test_existing_screen_maps_known_groups_and_preserves_unknown_absolute_units(readback: dict) -> None:
    screen = deepcopy(readback['market_screen'])
    original_screen = deepcopy(screen)
    attention = readback['research_attention']

    ledger = _ledger(screen, attention)
    decisions = ledger['decisions']
    statuses = Counter(row['decision_status'] for row in decisions)
    groups = Counter(row['source_group'] for row in decisions)

    assert ledger['source_input_identity'] == readback['market_screen_evidence']['input_identity']
    assert ledger['source_input_identity'] == readback['market_screen']['input_identity']
    assert ledger['RESEARCH_ONLY'] is True
    assert ledger['production_allowed'] is False
    assert ledger['buy_gate_updated'] is False
    assert ledger['orders_sent'] is False
    assert ledger['formal_selection_input'] is False
    assert all(row['RESEARCH_ONLY'] is True for row in decisions)
    assert all(row['production_allowed'] is False for row in decisions)
    assert all(row['buy_gate_updated'] is False for row in decisions)
    assert all(row['orders_sent'] is False for row in decisions)
    assert groups == {'strict': 214, 'near': 286, 'pending': 34, 'excluded': 159}
    assert statuses == {'SELECTED': 214, 'NEAR_WATCH': 286, 'EXCLUDED': 159, 'UNRESOLVED': 34}
    assert ledger['coverage']['source_group_counts'] == {
        'strict': 214, 'near': 286, 'pending': 34, 'excluded': 159, 'screen_unresolved': 0,
    }
    assert ledger['coverage']['selected_count'] == 214
    assert ledger['coverage']['near_watch_count'] == 286
    assert ledger['coverage']['excluded_count'] == 159
    assert ledger['coverage']['unresolved_count'] == 34
    pending = [row for row in decisions if row['source_group'] == 'pending']
    assert len(pending) == 34
    assert all(row['decision_status'] == 'UNRESOLVED' for row in pending)
    assert all(row['decision_reason_code'] == 'ORIGINAL_SCREEN_HISTORY_PENDING' for row in pending)

    for group in ('strict', 'near', 'excluded'):
        rows = screen[group]
        assert len(rows) > 0
        assert {row['volume_ratio_status'] for row in rows} == {'RELATIVE_RATIO_ONLY_UNIT_UNKNOWN'}
        assert {row['volume_unit_status'] for row in rows} == {'NOT_PROVEN'}
        assert {row['volume_relative_comparability_status'] for row in rows} == {
            'VERIFIED_SAME_RESPONSE_RAW_FIELD_UNIT_UNKNOWN'
        }
    all_screen_rows = [row for group in ('strict', 'near', 'pending', 'excluded') for row in screen[group]]
    assert all(row['volume_unit_status'] == 'NOT_PROVEN' for row in all_screen_rows)
    assert all(row['volume_ratio_status'] != 'OWNER_VERIFIED' for row in all_screen_rows)
    assert screen == original_screen
    assert all('volume_unit' not in row['source_metrics'] for row in decisions)
    assert all('SHARES' not in str(row['source_metrics']) for row in decisions)
    assert all('OWNER_VERIFIED' not in str(row['source_metrics']) for row in decisions)


@pytest.mark.parametrize(('path_key', 'sha_key'), [
    ('payload_path', 'payload_sha256'),
    ('artifact_path', 'artifact_sha256'),
])
def test_invalid_source_identity_keeps_affected_strict_row_unresolved(
    readback: dict, path_key: str, sha_key: str,
) -> None:
    screen = deepcopy(readback['market_screen'])
    row = screen['strict'][0]
    refs = row['source_refs']
    ref = next(ref for ref in refs if path_key in ref)
    ref[sha_key] = 'not-a-sha256'
    matching_card = next(card for card in screen['cards'] if card['code'] == row['code'])
    matching_ref = next(ref for ref in matching_card['source_refs'] if path_key in ref)
    matching_ref[sha_key] = 'not-a-sha256'

    ledger = _ledger(screen, readback['research_attention'])
    decision = next(item for item in ledger['decisions'] if item['symbol'] == row['code'])
    assert decision['decision_status'] == 'UNRESOLVED'
    assert decision['decision_reason_code'] == 'REBOUND_SCREEN_ROW_SOURCE_REFS_UNVERIFIED'


def test_missing_manifest_sha_keeps_affected_row_unresolved(readback: dict) -> None:
    screen = deepcopy(readback['market_screen'])
    row = screen['strict'][0]
    ref = row['source_refs'][0]
    matching_card = next(card for card in screen['cards'] if card['code'] == row['code'])
    matching_ref = matching_card['source_refs'][0]
    ref.pop('manifest_sha256')
    matching_ref.pop('manifest_sha256')

    ledger = _ledger(screen, readback['research_attention'])
    decision = next(item for item in ledger['decisions'] if item['symbol'] == row['code'])
    assert decision['decision_status'] == 'UNRESOLVED'
    assert decision['decision_reason_code'] == 'REBOUND_SCREEN_ROW_SOURCE_REFS_UNVERIFIED'


def test_row_session_mismatch_keeps_affected_row_unresolved(readback: dict) -> None:
    screen = deepcopy(readback['market_screen'])
    row = screen['strict'][0]
    row['verified_session'] = 20261008
    matching_card = next(card for card in screen['cards'] if card['code'] == row['code'])
    matching_card['verified_session'] = 20261008

    ledger = _ledger(screen, readback['research_attention'])
    decision = next(item for item in ledger['decisions'] if item['symbol'] == row['code'])
    assert decision['decision_status'] == 'UNRESOLVED'
    assert decision['decision_reason_code'] == 'REBOUND_SCREEN_ROW_DATE_OR_QUALIFICATION_MISMATCH'
