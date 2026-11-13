import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ops.prepare_review_core_logical_candidate import apply_overlay
from ops.research_panel_logical import META, anchor_bytes, descriptor, digest
from ops.review_core_logical_selector import LogicalSelector, candidate_selector


FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
SOURCE = '20261113'


def create_anchor(root, *, producer_pit=False, meta_pit=False, date=SOURCE):
    anchor = root / 'selector.parquet'
    receipt = root / 'receipt.json'
    block = root / 'block.parquet'
    metadata = dict(asof_date=int(date), generation_id='fixture', generation_manifest_path=str(receipt),
                    pit_certified=meta_pit, **FLAGS)
    rows = pa.table({
        'trade_date': ['20261112', SOURCE], 'ts_code': ['600000.SH', '600000.SH'],
        'name': ['Historical', 'Current'],
    })
    pq.write_table(rows, block)
    schema = rows.schema.with_metadata({META: json.dumps(metadata).encode()})
    anchor.write_bytes(anchor_bytes(schema, [descriptor(block)], rows=2))
    receipt.write_text(json.dumps(dict(
        schema='a_share_qfq_panel_v1', status='CANDIDATE_READY', target_date=int(date), generation_id='fixture',
        candidates={'selector': str(anchor)}, candidate_sha256={'selector': digest(anchor)},
        pit_certified=producer_pit, **FLAGS,
    )))
    return anchor, {'anchor_sha256': digest(anchor), 'producer_sha256': digest(receipt)}


def test_reads_exact_date_through_owner_and_preserves_original_false_pit(tmp_path, monkeypatch):
    anchor, sha = create_anchor(tmp_path)
    monkeypatch.setenv('V4_REVIEW_LOGICAL_SELECTOR_SHA256', sha['anchor_sha256'])
    monkeypatch.setenv('V4_REVIEW_LOGICAL_PRODUCER_RECEIPT_SHA256', sha['producer_sha256'])
    reader = candidate_selector(anchor, SOURCE, expected_sha256=sha['anchor_sha256'])
    assert reader.evidence()['row_count'] == 1
    assert reader.evidence()['producer_pit_certified'] is False
    assert reader.exact(['name']).to_pylist() == [{'name': 'Current'}]
    batches = reader.scanner(columns=['name'], batch_size=1).to_batches()
    assert [row for batch in batches for row in batch.to_pylist()] == [{'name': 'Historical'}, {'name': 'Current'}]
    assert candidate_selector(tmp_path / 'block.parquet', SOURCE) is None
    with pytest.raises(ValueError, match='EXPECTED_IDENTITY_MISSING_OR_CONFLICT'):
        candidate_selector(anchor, SOURCE, expected_sha256='a' * 64)


@pytest.mark.parametrize('changed', ['anchor_sha256', 'producer_sha256', 'date', 'pit_conflict', 'exact_date_missing'])
def test_binding_rejects_sha_date_or_owner_certification_conflict(tmp_path, changed):
    target = '20261116' if changed == 'exact_date_missing' else SOURCE
    anchor, sha = create_anchor(tmp_path, producer_pit=changed == 'pit_conflict', date=target)
    if changed in sha:
        sha[changed] = 'a' * 64
    if changed == 'date':
        target = '20261112'
    with pytest.raises(ValueError, match='REVIEW_CORE_LOGICAL_'):
        LogicalSelector.open(anchor, target, **sha).evidence()


def test_overlay_rejects_unrecognized_review_core_bytes():
    with pytest.raises(ValueError, match='REVIEW_CORE_BASE_SHA_MISMATCH'):
        apply_overlay('macos_daily.py', b'foreign role')
