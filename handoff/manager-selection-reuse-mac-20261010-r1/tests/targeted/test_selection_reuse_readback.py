"""Original CLI readback against real owner routes with synthetic source inputs.

Cases follow the fixed repository's existing handoff regression design. No
network socket, real announcement, production receipt or live clock is used.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

import selection_reuse_fixture as fixture
from test_selection_reuse_announcement import (
    PUBLICATION, TARGET, registered_inputs, source,
)
from ops import run_manager_daily_announcement as cli
from v4.manager_research.workspace_projection import digest


@pytest.fixture
def imported(source, monkeypatch):
    product, registration, _ = registered_inputs(source)
    with fixture._client(source) as client:
        response = fixture._import(client, registration)

        def original_route(api_base, path, *, method='GET', payload=None):
            assert api_base == 'http://127.0.0.1:8873'
            assert method == 'GET' and payload is None
            result = client.get(path)
            assert result.status_code == 200, result.text
            return result.json()

        monkeypatch.setattr(cli, '_request', original_route)
        yield SimpleNamespace(service=source, client=client, product=product,
                              imported=response, root=source.store.root)


def readback():
    return cli._readback(SimpleNamespace(target_date=TARGET,
        publication_date=PUBLICATION, api_base='http://127.0.0.1:8873'))


def test_original_cli_accepts_current_complete_owner_receipt(imported):
    before = fixture._snapshot(imported.root)
    result = readback()
    assert result['status'] == 'OWNER_READBACK_VERIFIED'
    assert result['product_sha256'] == imported.product['sha256']
    assert result['owner_receipt_sha256'] == imported.imported['owner_import_receipt']['sha256']
    assert fixture._snapshot(imported.root) == before


@pytest.mark.parametrize('mutation', [
    'missing_chain', 'unverified_chain', 'product_sha256', 'source_manifest_sha256',
    'evidence_run_id', 'handoff_manifest_sha256', 'agent_judgment_receipt_sha256',
    'owner_import_receipt_sha256',
])
def test_original_cli_rejects_missing_or_mismatched_chain(imported, monkeypatch, mutation):
    value = imported.client.get('/api/v4/manager/research/announcements/analysis',
        params={'date': TARGET, 'publication_date': '20261008'}).json()
    if mutation == 'missing_chain':
        value.pop('consumption_validation')
    elif mutation == 'unverified_chain':
        value['consumption_validation']['validation_status'] = 'CANNOT_CONFIRM'
    else:
        value['consumption_validation'][mutation] = 'f' * (32 if mutation == 'evidence_run_id' else 64)
    before = fixture._snapshot(imported.root)
    monkeypatch.setattr(cli, '_request', lambda *a, **k: deepcopy(value))
    with pytest.raises(ValueError, match=(
        'ANNOUNCEMENT_(ANALYSIS_OWNER_READBACK_CHAIN_INVALID|'
        'OWNER_IMPORT_RECEIPT_HANDOFF_BINDING_INVALID)'
    )):
        readback()
    assert fixture._snapshot(imported.root) == before


def test_original_cli_preserves_validated_legacy_receipt_bytes(imported):
    path = fixture.analysis.product_path(imported.service.store, TARGET, PUBLICATION).with_name(
        'owner_import_receipt.v1.json')
    receipt = json.loads(path.read_text())
    for key in ('source_manifest_sha256', 'evidence_run_id',
                'handoff_manifest_sha256', 'agent_judgment_receipt_sha256'):
        receipt.pop(key)
    receipt.pop('sha256')
    receipt['sha256'] = digest(receipt)
    path.write_text(json.dumps(receipt))
    before = fixture._snapshot(imported.root)
    result = readback()
    assert result['owner_receipt_sha256'] == receipt['sha256']
    assert fixture._snapshot(imported.root) == before
