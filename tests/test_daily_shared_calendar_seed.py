import pytest

from ops import research_panel_daily_product as product


def source_context_for_calendar_seed():
    context = object.__new__(product.SourceContext)
    context.generation = 'generation-20261119'
    context.target = 20261119
    context.identity = {'generation': context.generation, 'asof': context.target, 'historical_PIT': False}
    context.config_ref = {'path': '/pinned/source-config.json', 'sha256': 'a' * 64}
    context.config = {}
    context.calendars = {
        'SH': [20261118, 20261119, 20261120, 20261225],
        'SZ': [20261118, 20261119, 20261120, 20261225],
        'BJ': [20261118, 20261119, 20261120, 20261225],
    }
    return context


def test_shared_calendar_seed_preserves_future_days_and_list_values():
    source = source_context_for_calendar_seed()
    seed = source.export_calendar_seed()

    restored = product.SourceContext._restore_calendar_seed(source, seed)

    assert restored == source.calendars
    assert all(isinstance(days, list) for days in restored.values())
    assert 20261225 in restored['SH']


def test_shared_calendar_seed_rejects_payload_or_source_identity_drift():
    source = source_context_for_calendar_seed()
    seed = source.export_calendar_seed()
    changed_payload = {**seed['payload'], 'generation': 'other-generation'}
    changed_seed = dict(payload=changed_payload, sha256=product.digest(changed_payload))

    with pytest.raises(ValueError, match='DAILY_SHARED_CALENDAR_SOURCE_IDENTITY_CONFLICT'):
        product.SourceContext._restore_calendar_seed(source, changed_seed)

    tampered_seed = {**seed, 'payload': {**seed['payload'], 'calendars': {**seed['payload']['calendars'],
        'SH': [20261119, 20261118]}}}
    with pytest.raises(ValueError, match='DAILY_SHARED_CALENDAR_SOURCE_IDENTITY_CONFLICT'):
        product.SourceContext._restore_calendar_seed(source, tampered_seed)
