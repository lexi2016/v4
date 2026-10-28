"""02: an immutable historical backfill must not be returned as a formal Stage result.

Run in the full application with:
    python -m pytest -q tests/test_hk_connect_backfill_formal_guard.py
The extracted-source harness supplies only imports omitted from this problem package.
"""
from __future__ import annotations
from pathlib import Path
import pytest
from stage_center.consumer import StageSelectionConsumer, _project_market

DATE = '20261009'
STAGE = 'STAGE_0925'
SHA = 'a' * 64


def envelope(*, marker=None, status='READY'):
    evidence = [] if marker is None else [marker]
    return {
        'trade_date': DATE, 'stage_id': STAGE, 'market': 'HK_CONNECT',
        'selection_status': status, 'source_status': 'READY',
        'raw_artifact_sha256': SHA, 'algorithm_sha256': 'b'*64,
        'artifact_id': 'stage-test-immutable', 'run_id': 'test-immutable-run',
        'selected_rows': 1, 'source_rows': 1, 'requested_rows': 100,
        'source_evidence': evidence, 'cannot_confirm': [],
        'rows': [{'code': 'HK.00001', 'rank': 1, 'score': 1.0,
                  'lane_evidence': ['test-stage-reason']}],
    }


class VerifiedStoreStub:
    """Models a SelectionStore whose own SHA trio has already been verified."""
    def __init__(self, payload, root):
        self.payload = payload
        self.root = Path(root)

    def read_verified(self, trade_date, stage_id, market):
        assert (trade_date, stage_id, market) == (DATE, STAGE, 'HK_CONNECT')
        return self.payload

    def _latest(self):
        return {'entries': {self._key(DATE, STAGE, 'HK_CONNECT'): {
            'run_id': self.payload['run_id'],
            'manifest_sha256': 'c'*64,
            'receipt_sha256': 'd'*64,
            'artifact_sha256': 'e'*64,
        }}}

    def _verify_run(self, date, stage, market, run):
        if run != self.payload['run_id']:
            raise ValueError('selection run is not bound')
        return {'run_id': run, 'manifest_sha256': 'c'*64,
                'receipt_sha256': 'd'*64, 'artifact_sha256': 'e'*64,
                'envelope': self.payload, 'trade_date': date,
                'stage_id': stage, 'market': market}

    @staticmethod
    def _key(date, stage, market):
        return f'{date}/{stage}/{market}'


def consumer_for(payload, tmp_path):
    reader = StageSelectionConsumer.__new__(StageSelectionConsumer)
    reader.store = VerifiedStoreStub(payload, tmp_path)
    reader.execution_receipt_root = None
    reader.runner_receipt_root = None
    reader.a_name_pool_root = None
    reader._a_name_authority_cache = {}
    return reader


@pytest.mark.parametrize('marker', [
    'recovery_mode=HISTORICAL_BACKFILL',
    'due_status=HISTORICAL_BACKFILL',
    'HISTORICAL_BACKFILL',
    'selection_mode=BACKFILL',
])
def test_all_backfill_evidence_is_tagged(marker):
    projected = _project_market('HK_CONNECT', envelope(marker=marker), trade_date=DATE, stage_id=STAGE)
    assert projected['selection_mode'] == 'BACKFILL'
    assert len(projected['rows']) == 1


@pytest.mark.parametrize('marker', [
    'recovery_mode=HISTORICAL_BACKFILL',
    'due_status=HISTORICAL_BACKFILL',
    'selection_mode=BACKFILL',
])
def test_default_consumer_refuses_backfill_from_ordinary_latest(marker, tmp_path):
    reader = consumer_for(envelope(marker=marker), tmp_path)
    product = reader.get(DATE, STAGE, markets=['HK_CONNECT'])['markets']['HK_CONNECT']
    assert product['status'] == 'CANNOT_CONFIRM'
    assert product['selected_rows'] is None  # unknown/unverified, not zero
    assert product['rows'] == []
    assert 'BACKFILL_NOT_FORMAL_STAGE_SELECTION' in product['cannot_confirm']


def test_explicit_stage_backfill_remains_visible_with_backfill_label(tmp_path):
    reader = consumer_for(envelope(marker='recovery_mode=HISTORICAL_BACKFILL'), tmp_path)
    product = reader.get(DATE, STAGE, markets=['HK_CONNECT'],allow_backfill=True)['markets']['HK_CONNECT']
    assert product['selection_mode'] == 'BACKFILL'
    assert product['runner_receipt_verified'] is False
    assert product['runner_receipt_status'] == 'CANNOT_CONFIRM'
    assert product['selected_rows'] == 1
    assert len(product['rows']) == 1


def test_formal_original_stage_is_unchanged(tmp_path):
    reader = consumer_for(envelope(), tmp_path)
    product = reader.get(DATE, STAGE, markets=['HK_CONNECT'])['markets']['HK_CONNECT']
    assert product['status'] == 'READY'
    assert product['selected_rows'] == 1
    assert len(product['rows']) == 1
    assert product.get('selection_mode') != 'BACKFILL'


def test_cannot_confirm_row_is_not_relabelled_ready(tmp_path):
    reader=consumer_for(envelope(status='CANNOT_CONFIRM'), tmp_path)
    product=reader.get(DATE, STAGE, markets=['HK_CONNECT'])['markets']['HK_CONNECT']
    assert product['status'] == 'CANNOT_CONFIRM'
    assert len(product['rows']) == 1


def test_original_hk_stage_formula_publish_then_verified_consumer_readback(tmp_path):
    """Offline engineering: original algorithm/store, not Mac PIT or scheduler."""
    from stage_center.selection import select_hk_0925_second_filter, SelectionStore
    payload = select_hk_0925_second_filter(
        [{'code': 'HK.00001', 'target_date': DATE, 'rank': 1,
          'auction_score': 0.73, 'second_filter_status': 'WATCH_ONLY',
          'preselect_lane': 'STRICT_0_2_READY'}],
        DATE, SHA, source_status='READY',
        source_evidence=('selection_contract=V3_TOP10_RECOMMENDATION',),
    )
    assert payload['selection_status'] == 'READY'
    assert payload['rows'][0]['action_level'] == 'NO_BUY'
    store = SelectionStore(tmp_path)
    published = store.publish(payload, market='HK_CONNECT')
    checked = store.read_verified(DATE, STAGE, 'HK_CONNECT')
    observed = StageSelectionConsumer(tmp_path).get(DATE, STAGE, markets=['HK_CONNECT'])
    market = observed['markets']['HK_CONNECT']
    assert published['run_id'] == checked['run_id'] == market['run_id']
    assert market['selection_status'] == 'READY'
    assert len(market['rows']) == 1
    assert market['rows'][0]['code'] == 'HK.00001'
    assert market['rows'][0]['action_level'] == 'NO_BUY'


def test_original_store_backfill_readback_never_promoted_to_formal(tmp_path):
    from stage_center.selection import select_hk_0925_second_filter, SelectionStore
    payload = select_hk_0925_second_filter(
        [{'code': 'HK.00001', 'target_date': DATE, 'rank': 1, 'auction_score': 0.5}],
        DATE, SHA, source_status='READY',
        source_evidence=('selection_contract=V3_TOP10_RECOMMENDATION',
                         'recovery_mode=HISTORICAL_BACKFILL'),
    )
    store=SelectionStore(tmp_path)
    store.publish(payload, market='HK_CONNECT')
    normal=StageSelectionConsumer(tmp_path).get(DATE, STAGE, markets=['HK_CONNECT'])['markets']['HK_CONNECT']
    assert normal['status']=='CANNOT_CONFIRM'
    assert normal['selected_rows'] is None
    assert normal['rows']==[]
    historical=StageSelectionConsumer(tmp_path).get(DATE, STAGE, markets=['HK_CONNECT'],allow_backfill=True)['markets']['HK_CONNECT']
    assert historical['selection_mode']=='BACKFILL'
    assert historical['run_id']==payload['run_id']
    assert historical['runner_receipt_verified'] is False
    assert len(historical['rows'])==1
