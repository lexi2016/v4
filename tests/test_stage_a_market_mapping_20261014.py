import pytest

from stage_center.live_collectors import _tdx_code


@pytest.mark.parametrize('code,expected', [
    ('A.510300', 'SH.510300'), ('A.512100', 'SH.512100'),
    ('A.920826', 'BJ.920826'), ('A.920275', 'BJ.920275'),
    ('A.159915', 'SZ.159915'), ('A.300308', 'SZ.300308'),
    ('A.600000', 'SH.600000'), ('A.688001', 'SH.688001'),
    ('A.830001', 'BJ.830001'), ('SH.510300', 'SH.510300'),
])
def test_stage_provider_exchange_matches_security_family(code, expected):
    assert _tdx_code(code) == expected
