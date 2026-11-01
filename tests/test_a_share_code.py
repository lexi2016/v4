"""A six-digit token is not automatically an A-share code.

Titles and filenames carry dates in the same shape ("更新261029",
"...-261030.pdf"). Accepting them invents an entity that no source data can
verify, and it then shows up in the research pool ranked by article count and
is isolated downstream as a missing symbol.
"""
from __future__ import annotations

import pytest

from contracts.a_share_code import a_share_symbol, canonical_a_share_code, is_a_share_code

# Codes that really appear in this system's pools, including the ones that look
# like dates because they start with 30.
REAL_CODES = [
    "600519", "601318", "603528", "605358", "688489",
    "000001", "001914", "002539", "003816", "000568",
    "300115", "300122", "301029", "300504", "301216",
    "920627", "510310", "563360", "159915",
    "430047", "830799", "872925",
]

DATE_SHAPED = ["261029", "261030", "251231", "260101"]


@pytest.mark.parametrize("code", REAL_CODES)
def test_real_codes_are_accepted(code):
    assert is_a_share_code(code)
    assert a_share_symbol(code) == f"A.{code}"
    assert canonical_a_share_code(code) == f"A.{code}"


@pytest.mark.parametrize("code", DATE_SHAPED)
def test_dates_are_not_codes(code):
    assert not is_a_share_code(code)
    assert a_share_symbol(code) == ""
    assert canonical_a_share_code(code) == ""


def test_a_filename_date_is_not_a_code():
    assert a_share_symbol("申万宏源-云图控股(002539)复合肥销量略下滑-261029.pdf") == "A.002539"
    assert a_share_symbol("开源电新】逸豪新材更新261029——黑马走到台前") == ""
    assert a_share_symbol("research-261030.pdf") == ""


def test_a_prefixed_date_is_still_not_a_code():
    assert canonical_a_share_code("A.261029") == ""
    assert canonical_a_share_code("SZ.261029") == ""
    assert a_share_symbol("A.261029") == ""


def test_short_and_long_tokens_are_rejected():
    for value in ("2610", "2610291", "HK.00700", "00700.HK", "", None):
        assert a_share_symbol(value) == ""
        assert canonical_a_share_code(value) == ""


def test_the_materializer_uses_the_validated_symbol():
    from domains.preselection_materializer import _a_symbol

    assert _a_symbol("261029") == ""
    assert _a_symbol("002539") == "A.002539"


def test_the_hourly_producer_uses_the_validated_code():
    from domains.research_hourly import canonical_stage_a_code

    assert canonical_stage_a_code("261029") == ""
    assert canonical_stage_a_code("300115") == "A.300115"


# --- defects found in review of the first version ---------------------------


def test_a_date_before_a_real_code_does_not_hide_it():
    assert a_share_symbol("261029 600519") == "A.600519"
    assert a_share_symbol("更新261029 贵州茅台600519") == "A.600519"
    assert a_share_symbol("261029,261030,600519") == "A.600519"


def test_a_code_must_not_be_a_prefix_of_a_longer_number():
    assert a_share_symbol("6005191") == ""
    assert a_share_symbol("x6005191y") == ""
    assert a_share_symbol("1600519") == ""
    assert a_share_symbol("600519") == "A.600519"


def test_a_real_code_with_a_market_suffix_still_resolves():
    assert a_share_symbol("600519.SH") == "A.600519"
    assert a_share_symbol("000001.SZ") == "A.000001"


def test_only_invalid_tokens_means_no_symbol():
    assert a_share_symbol("261029 261030 251231") == ""
