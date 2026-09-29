"""Boundary parsing tests, not real-article or OCR validation."""
import pytest
from wechat_article_fetch import _date_from_raw, _positive_int

@pytest.mark.parametrize("value", [True, False, 1.9, 1.0, "1.2", "1e3", 0, -1, None])
def test_counts_reject_non_positive_integer_values(value):
    with pytest.raises(ValueError):
        _positive_int(value, "image_count")

@pytest.mark.parametrize("value, expected", [(1,1),("2",2),(" 3 ",3)])
def test_counts_accept_positive_integers(value, expected):
    assert _positive_int(value,"image_count") == expected

@pytest.mark.parametrize("raw, expected", [
    ("2026-08-30T18:00:00Z","20260831"),
    ("2026-08-31T01:00:00+12:00","20260830"),
    ("2026-08-30T22:51:57+08:00","20260830"),
    ("20260830","20260830"),
    ("2026/08/30","20260830"),
])
def test_publication_timestamp_uses_china_calendar_date(raw, expected):
    assert _date_from_raw(raw) == expected


def test_invalid_iso_time_cannot_be_accepted_as_just_a_date():
    with pytest.raises(ValueError):
        _date_from_raw("2026-08-30T99:00:00+08:00")
