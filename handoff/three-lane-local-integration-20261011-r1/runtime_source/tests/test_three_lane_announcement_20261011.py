"""Synthetic registered evidence; real original service, store and HTTP owner.

The fixture is an unchanged, hash-verified original test helper. No live
announcement, reader judgement, owner run or natural execution is claimed.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from v4.manager_research import announcement_analysis as analysis
from v4.manager_research import workspace_announcements as consumption
from v4.manager_research.service import ManagerResearchJobService

_spec = importlib.util.spec_from_file_location('three_lane_announcement_fixture',
    Path(__file__).parent / 'three_lane_fixtures' / 'announcement.py')
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)


def _envelope(registered):
    return {key: registered[key] for key in
            ('evidence_run_id', 'handoff_manifest_sha256', 'product_sha256')} | {
        'schema_version': 'v4.manager_research.announcement_analysis_import_ref.v1'}


@pytest.fixture
def owner(tmp_path, monkeypatch):
    monkeypatch.setattr(consumption, '_now', lambda: fixture.NOW.isoformat())
    service = fixture._FixtureService(tmp_path / 'research-state')
    # Use the actual service method, including its dispatch into the original
    # analysis owner. Only the external catalog and clock are fixture inputs.
    service.import_announcement_analysis = (
        ManagerResearchJobService.import_announcement_analysis.__get__(service))
    yield service
    service.close()


def test_direct_owner_reference_import_and_http_get_share_receipt(owner):
    product, registered = fixture._fixture(owner)
    imported = owner.import_announcement_analysis(_envelope(registered))
    assert imported['import_status'] == 'IMPORTED'
    assert imported['analysis']['product_sha256'] == product['sha256']
    receipt = imported['owner_import_receipt']
    assert receipt['owner'] == 'ManagerResearchJobService.import_announcement_analysis'
    assert receipt['handoff_manifest_sha256'] == registered['handoff_manifest_sha256']
    assert imported['consumption_validation']['validation_status'] == 'VERIFIED'
    with fixture._client(owner) as client:
        read = client.get('/api/v4/manager/research/announcements/analysis', params={
            'date': fixture.TARGET, 'publication_date': fixture.PUBLICATION})
        assert read.status_code == 200, read.text
        assert read.json()['owner_import_receipt'] == receipt
        again = fixture._import(client, registered)
        assert again['import_status'] == 'ALREADY_IMPORTED'
        assert again['owner_import_receipt'] == receipt


def test_repeated_owner_import_preserves_first_availability(owner, monkeypatch):
    _, registered = fixture._fixture(owner)
    envelope = _envelope(registered)
    first = owner.import_announcement_analysis(envelope)
    before = fixture._snapshot(owner.store.root)
    monkeypatch.setattr(consumption, '_now', lambda: '2026-10-11T01:00:00+00:00')
    second = owner.import_announcement_analysis(envelope)
    assert second['owner_import_receipt'] == first['owner_import_receipt']
    assert fixture._snapshot(owner.store.root) == before
    proof = consumption.read_analysis_consumption(owner, fixture.TARGET,
        fixture.PUBLICATION, cutoff='2026-10-08T01:30:00+00:00')
    assert proof['status'] == 'CONSUMED'


def test_two_owner_instances_reuse_one_receipt(owner):
    _, registered = fixture._fixture(owner)
    other = fixture._FixtureService(owner.store.root)
    other.catalogs = deepcopy(owner.catalogs)
    other.import_announcement_analysis = (
        ManagerResearchJobService.import_announcement_analysis.__get__(other))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda service:
                service.import_announcement_analysis(_envelope(registered)), [owner, other]))
        assert {result['import_status'] for result in results} == {'IMPORTED', 'ALREADY_IMPORTED'}
        assert results[0]['owner_import_receipt'] == results[1]['owner_import_receipt']
    finally:
        other.close()


@pytest.mark.parametrize('key,value', [
    ('handoff_manifest_sha256', 'f' * 64), ('product_sha256', 'f' * 64),
    ('evidence_run_id', 'f' * 32), ('unexpected', True),
])
def test_unregistered_or_misbound_reference_never_publishes(owner, key, value):
    _, registered = fixture._fixture(owner)
    envelope = _envelope(registered) | {key: value}
    before = fixture._snapshot(owner.store.root)
    with pytest.raises(ValueError):
        owner.import_announcement_analysis(envelope)
    assert fixture._snapshot(owner.store.root) == before


def test_legacy_product_readable_but_never_receipted_as_reviewed(owner):
    product, _ = fixture._fixture(owner, reviewed=False)
    result = owner.import_announcement_analysis(product)
    assert result['analysis']['status'] == 'VERIFIED'
    assert not analysis.product_path(owner.store, fixture.TARGET,
        fixture.PUBLICATION).with_name('owner_import_receipt.v1.json').exists()
    proof = consumption.read_analysis_consumption(owner, fixture.TARGET,
        fixture.PUBLICATION, cutoff='2026-10-08T01:30:00+00:00')
    assert proof['consumed'] is False
    assert proof['validation_status'] == 'CANNOT_CONFIRM'


def test_invalid_existing_receipt_is_not_overwritten(owner):
    product, registered = fixture._fixture(owner)
    path = analysis.product_path(owner.store, fixture.TARGET,
        fixture.PUBLICATION).with_name('owner_import_receipt.v1.json')
    owner.store._write_atomic(path, {'schema_version': 'invalid-existing-receipt'})
    raw = path.read_bytes()
    with pytest.raises(ValueError):
        owner.import_announcement_analysis(_envelope(registered))
    assert path.read_bytes() == raw
    # Reject before a product can be partially imported beside a known conflict.
    assert not analysis.product_path(owner.store, fixture.TARGET, fixture.PUBLICATION).exists()
