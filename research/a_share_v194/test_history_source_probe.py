"""Only the new bounded source-probe codec and comparison behaviors."""
import pytest

import history_source_probe as probe


def payload(day=20261019, volume=12345678):
    return probe.DAY.pack(day, 1001, 1100, 900, 1005, 987654.5, volume, 0)


def test_source_probe_preserves_producer_native_units():
    row = probe.decode_day(payload(), "000001.SZ")[0]
    assert row["open"] == 10.01
    assert row["close"] == 10.05
    assert row["vol"] == 12345678
    assert row["amount"] == 987654.5


def test_source_probe_rejects_trailing_or_duplicate_day():
    with pytest.raises(ValueError, match="DAY_TRAILING_BYTES"):
        probe.decode_day(payload() + b"x", "000001.SZ")
    with pytest.raises(ValueError, match="DAY_DATE_NOT_SORTED_UNIQUE"):
        probe.decode_day(payload() * 2, "000001.SZ")


def test_source_probe_distinguishes_float32_and_true_conflicts():
    left = probe.decode_day(payload(), "000001.SZ")
    right = [{**left[0], **{key: probe.float32(float(left[0][key])) for key in probe.FIELDS}}]
    summary, conflicts = probe.compare_rows(left, right, code="000001.SZ", left_name="native", right_name="panel")
    assert summary["field_counts"]["open"]["exact_equal"] == 0
    assert summary["field_counts"]["open"]["equal_after_both_float32"] == 1
    assert conflicts == []
    right[0]["close"] += 0.01
    summary, conflicts = probe.compare_rows(left, right, code="000001.SZ", left_name="native", right_name="panel")
    assert summary["field_counts"]["close"]["different_after_both_float32"] == 1
    assert conflicts[0]["different_fields"] == "close"


def test_source_probe_reports_volume_ratio_without_conversion():
    left = probe.decode_day(payload(volume=10000), "000001.SZ")
    right = [{**left[0], "vol": 100}]
    summary, conflicts = probe.compare_rows(left, right, code="000001.SZ", left_name="native", right_name="other")
    assert summary["volume_ratio_observations"]["right_equals_left_div_100"] == 1
    assert conflicts[0]["left_vol"] == 10000
    assert conflicts[0]["right_vol"] == 100
    assert left[0]["vol"] == 10000
    assert summary["adjustment_verdict"] == "CANNOT_CONFIRM_FROM_PAIRWISE_PARITY_ALONE"


def test_r2_explicit_panel_volume_alias_preserves_values_and_rejects_wrong_alias(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    for alias in ("vol", "volume"):
        path = tmp_path / (alias + ".parquet")
        row = probe.decode_day(payload(volume=12345678), "000001.SZ")[0]
        row[alias] = row.pop("vol")
        pq.write_table(pa.Table.from_pylist([row]), path)
        binding = dict(path=str(path), stat=probe.file_stat(path), volume_field=alias)
        by_code, metadata = probe.read_panel(binding, ["000001.SZ"])
        assert by_code["000001.SZ"][0]["vol"] == 12345678
        assert set(by_code["000001.SZ"][0]) == set(probe.COLUMNS)
        assert metadata["volume_conversion"] == "COLUMN_RENAME_ONLY_VALUE_UNCHANGED"
        wrong_alias = "volume" if alias == "vol" else "vol"
        with pytest.raises(ValueError, match="PANEL_REQUIRED_COLUMNS_MISSING"):
            probe.read_panel({**binding, "volume_field": wrong_alias}, ["000001.SZ"])
