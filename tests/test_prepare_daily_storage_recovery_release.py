from copy import deepcopy
from pathlib import Path

import pytest

from ops import prepare_daily_storage_recovery_release as release
from tests.test_prepare_a925_mainclosure_release import main_service, old_config


def test_owner_repin_preserves_seven_exact_history_and_transition():
    config = old_config()
    config['research_historical_owner_bindings'].append(dict(app_root='/seventh/app', release_id='seventh', manifest_sha256='seven'))
    before = deepcopy(config)
    result = release.stage_config_for_main(config, main_service(), 'storage-stage')
    assert config == before
    assert result['research_historical_owner_bindings'][:7] == before['research_historical_owner_bindings']
    assert result['research_historical_owner_bindings'][7] == before['research_owner_binding']
    assert result['research_transition_owner_binding'] == before['research_transition_owner_binding']
    assert result['research_owner_binding']['manifest_sha256'] == 'new-sha'
    result.pop('research_historical_owner_bindings')
    result.pop('research_owner_binding')
    result.pop('release_id')
    for key in result: assert result[key] == before[key]
    with pytest.raises(ValueError, match='SEVEN_HISTORY'):
        release.stage_config_for_main(old_config(), main_service(), 'storage-stage')


def test_reuses_accepted_transaction_with_local_validator(monkeypatch):
    events = []
    def transaction(packet, review, *, rollback=False):
        validate(packet)
        return rollback
    monkeypatch.setattr(release.prior, 'cutover', transaction)
    monkeypatch.setattr(release, 'validate', lambda value: events.append(value))
    assert release.cutover('packet', 'review', rollback=True) is True
    assert events == ['packet']


def test_stage_runtime_variant_changes_only_exact_history_capacity():
    delta = Path(release.__file__).resolve().parents[1]/'docs/handoffs/daily_storage_release_20261110/DELTA.json'
    import json
    entries = json.loads(delta.read_text())['entries']
    entry = entries[1]
    candidate = Path(entry['source']).read_text()
    baseline = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-a925-readiness-20261110-r3/v4-a925-readiness-20261110-r3-stage/app')/entry['target']
    assert candidate.replace('len(historical) > 8', 'len(historical) > 7') == baseline.read_text()
