## Source excerpt: `tests/test_us_equity_calendar.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/futu-industry-us-20261016-r1/app/tests/test_us_equity_calendar.py`

Original full-file SHA-256: `eda8247301bcbbd5ab96c6ae3e865775d819cc834d3a6ecba1db6c178b963fc2`

Release/worktree group: `us_digest`

Existing DST-aware session offset and latest completed US session tests.

### Full-source lines 65-86

```python

def test_capture_slot_width_and_ny_offsets_remain_explicit_across_dst_and_half_day():
    cases = (
        ("20260115", "PRE_OPEN", -5),
        ("20260924", "PRE_OPEN", -4),
        ("20261127", "POST_CLOSE", -5),
    )
    for session_date, phase, offset_hours in cases:
        start, end = us_capture_window(session_date, phase)
        assert (end - start).total_seconds() == 5 * 60
        assert start.utcoffset().total_seconds() == offset_hours * 60 * 60


def test_manager_cutoff_resolves_previous_completed_us_session_with_dst():
    cutoff = datetime.fromisoformat("2026-09-24T09:27:35.408396+08:00")
    resolved = latest_completed_session(cutoff)
    assert resolved.session_date == "20260923"
    assert resolved.close_at.isoformat().startswith("2026-09-23T16:00:00-04:00")


def test_weekend_observation_rolls_to_friday_without_guessing_a_weekday():
    observed = datetime(2026, 9, 27, 12, tzinfo=ZoneInfo("Asia/Hong_Kong"))
    assert latest_completed_session(observed).session_date == "20260925"

```
