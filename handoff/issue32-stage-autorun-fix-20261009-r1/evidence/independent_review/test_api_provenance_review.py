"""Independent controls for the coordinator's existing-provenance date finding."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
from test_api_same_date import accepts, calendar_authority, _pool, _provenance


def test_present_provenance_cannot_authorize_old_price_and_eligibility(accepts):
    pool = _pool(price='20260930', eligibility='20260930')
    pool['historical_provenance'] = _provenance(pool)
    assert accepts(pool, '20261009') is False


@pytest.mark.parametrize('capture', [
    'not-a-timestamp', '2026-10-08T17:30:00',
    '2026-09-30T17:30:00+08:00', '2026-10-09T00:01:00+08:00',
])
def test_present_provenance_capture_must_bind_eligibility_day(accepts, capture):
    pool = _pool()
    provenance = _provenance(pool)
    provenance['eligibility_source_captured_at'] = capture
    pool['historical_provenance'] = provenance
    assert accepts(pool, '20261009') is False
