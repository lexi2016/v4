from __future__ import annotations

import gzip
import random
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ops import pft_sb_v13_act009 as act009
from ops import pft_sb_v13_act009b as study


def _signal(**overrides):
    row = {
        "anchor_age": 0.0, "low_held_anchor": 1.0, "recent_below_pair": 0.0,
        "close_bbi_pct": 0.0, "vol5_vs_prior15": 1.0, "range5_vs_prior15": 1.0,
        "d_open_close_prev_close": 0.0, "d_vr5": 3.0, "close_vs_prior10_high": 0.0,
        "ret_1": -0.03, "ret_5": -0.05, "close_white_pct": -0.02,
        "d_upper_wick_prev_close": 0.025, "close_yellow_pct": 0.25,
        "ret_20": 0.30, "white_yellow_spread_pct": 0.005,
        "d_range_prev_close": 0.045, "close_vs_trailing30_high": -0.08,
        "rebuild": True, "rebuild_v13": False, "pullback": True, "readvance": True,
    }
    row.update(overrides)
    return row


def test_f1_exact_is_standalone_act008_and_repair_is_additional():
    raw = pd.DataFrame([_signal(), _signal(rebuild_v13=True)])
    result, counts = study._add_f1_f4(raw)

    assert result["f1_exact"].tolist() == [True, True]
    assert result["f1_with_repair"].tolist() == [False, True]
    assert result["f1_state"].tolist() == ["PASS", "PASS"]
    assert result["f1_with_repair_state"].tolist() == ["FAIL", "PASS"]
    assert counts["f1_exact_rows"] == 2
    assert counts["f1_with_repair_rows"] == 1
    assert result.loc[1, "clean_rebuild"]


def test_f3_veto_state_uses_veto_allow_unknown_and_strict_edges():
    rows = [
        _signal(rebuild=False, pullback=False, readvance=False, rebuild_v13=False),
        _signal(d_vr5=3.00001),
        _signal(close_yellow_pct=0.25001, ret_20=0.30),
        _signal(d_upper_wick_prev_close=0.035),
        _signal(anchor_age=25.0),
        _signal(anchor_age=25.01),
        _signal(anchor_age=np.nan),
    ]
    result, _ = study._add_f1_f4(pd.DataFrame(rows))
    assert result["f3_state"].tolist() == ["ALLOW", "VETO", "ALLOW", "VETO", "ALLOW", "VETO", "UNKNOWN"]


def test_f2_and_f4_branch_thresholds_are_inclusive_except_readvance_open():
    raw = pd.DataFrame([
        _signal(rebuild=False, rebuild_v13=False, pullback=True, readvance=False),
        _signal(rebuild=False, rebuild_v13=False, pullback=False, readvance=True,
                d_open_close_prev_close=0.0),
        _signal(rebuild=True, rebuild_v13=True, pullback=False, readvance=False,
                d_open_close_prev_close=0.0, d_range_prev_close=0.06),
    ])
    result, _ = study._add_f1_f4(raw)
    assert result.loc[0, "f2_exact"]
    assert result.loc[0, "f4_pullback_confirmed"]
    assert not result.loc[1, "f4_readvance_confirmed"]
    assert result.loc[2, "f1_with_repair"]
    assert result.loc[2, "f4_rebuild_confirmed"]
    assert not result.loc[1, "clean_readvance"]


def test_f5_uses_exact_prior_sixty_and_fixed_boundaries():
    dates = [value.strftime("%Y%m%d") for value in pd.date_range("2026-01-01", periods=62, freq="B")]
    counts = list(range(1, 62)) + [500]
    rows = [{"trade_date": day, "union": True} for day, count in zip(dates, counts)
            for _ in range(count)]
    result, meta = study._add_f5_crowding(pd.DataFrame(rows), dates)
    per_day = result.drop_duplicates("trade_date").set_index("trade_date")

    assert pd.isna(per_day.loc[dates[59], "crowding_rolling_p25"])
    assert per_day.loc[dates[60], "crowding_rolling_p25"] == np.quantile(np.arange(1, 61), 0.25)
    assert per_day.loc[dates[61], "crowding"] == 500
    assert per_day.loc[dates[61], "f5_fixed_high"]
    assert per_day.loc[dates[61], "f5_blocked"]
    assert meta["rolling_p25_known_dates"] == 2


def test_candidate_shards_split_by_rows_are_deterministic_and_readable(tmp_path: Path):
    rows = []
    for split_day in ("20260601", "20260901"):
        for index in range(10):
            payload = random.Random(f"{split_day}:{index}").randbytes(512).hex()
            rows.append({"trade_date": split_day, "ts_code": f"{index:06d}.SZ", "payload": payload})
    projection = pd.DataFrame(rows)
    receipts = study._write_candidate_shards(projection, tmp_path, max_shard_bytes_exclusive=900)

    assert {receipt["split"] for receipt in receipts} == {"train", "oos"}
    assert sum(receipt["rows"] for receipt in receipts) == len(projection)
    assert all(receipt["bytes"] < 900 and receipt["gzip_mtime"] == 0 for receipt in receipts)
    assert all(receipt["path"].startswith("CODEX_MAC_ACT-009B_") for receipt in receipts)
    hashes = [receipt["sha256"] for receipt in receipts]
    second = tmp_path / "second"
    second.mkdir()
    receipts_second = study._write_candidate_shards(projection, second, max_shard_bytes_exclusive=900)
    assert hashes == [receipt["sha256"] for receipt in receipts_second]
    for receipt in receipts:
        assert len(gzip.decompress((tmp_path / receipt["path"]).read_bytes())) == receipt["uncompressed_bytes"]


def test_target_contract_keeps_censored_labels_blank_and_exact_date_mapping():
    market_dates = ["20260105", "20260106", "20260107", "20260108", "20260109",
                    "20260112", "20260113", "20260114", "20260115", "20260116", "20260119"]
    frame = pd.DataFrame({
        "trade_date": [market_dates[0], market_dates[6], market_dates[10]],
        "return_t1": [0.01, 0.02, np.nan], "return_t3": [0.03, 0.04, np.nan],
        "return_t5": [0.05, 0.01, np.nan], "return_t10": [0.06, np.nan, np.nan],
        "path_observable_t1": [True, True, False], "path_observable_t3": [True, True, False],
        "path_observable_t5": [True, False, False], "path_observable_t10": [True, False, False],
        "min_path_dd_t5": [-0.02, np.nan, np.nan], "min_path_dd_t10": [-0.03, np.nan, np.nan],
        "top200_member_t1": [True, pd.NA, pd.NA],
    })
    result = study._attach_target_contract(frame, market_dates)
    assert result.loc[0, "target_t5_date"] == market_dates[5]
    assert result.loc[0, "target_t5_success"] == 1.0
    assert pd.isna(result.loc[1, "target_t5_success"])
    assert bool(result["in_next_top200"].iloc[0])
    assert pd.isna(result["in_next_top200"].iloc[1])


def test_training_target_and_purge_use_the_clean_candidate_column():
    market_dates = [value.strftime("%Y%m%d") for value in pd.bdate_range("2026-08-17", periods=13)]
    frame = pd.DataFrame({
        "trade_date": [market_dates[0], market_dates[1], market_dates[11]],
        "ts_code": ["000000.SZ", "000000.SZ", "000000.SZ"],
        "clean_union": [True, False, True], "v13_candidate_union": [False, True, True],
        "return_t5": [0.04, 0.09, 0.05], "min_path_dd_t5": [-0.04, -0.01, -0.02],
        "path_observable_t5": [True, True, True],
        "_anchor_date": ["20260801", "", "20260801"],
        "rebuild_episode_id": ["", "", "REPAIR-A"],
    })
    labeled, _ = act009._add_b_training_labels(frame, market_dates, candidate_column="clean_union")
    split_frame, split = act009._episode_split(labeled, candidate_column="clean_union")

    assert labeled.loc[0, "b_training_target"] == 1.0
    assert pd.isna(labeled.loc[1, "b_training_target"])
    assert pd.isna(labeled.loc[2, "b_training_target"])
    assert split["cross_split_canonical_k_groups"] == 1
    assert not split["train_mask"].iloc[0]
    assert split["oos_mask"].iloc[2]
    assert split_frame["_canonical_k_group"].iloc[2] == "000000.SZ|K|20260801"


def test_candidate_projection_is_fixed_window_and_allowlist_has_no_targets():
    values = {name: 0 for name in study.BASE_EXPORT_COLUMNS}
    values.update({"trade_date": ["20251031", "20251103"],
                   "ts_code": ["000001.SZ", "000002.SZ"], "market_type": ["SZ", "SZ"],
                   "union": [True, True], "v13_candidate_union": [False, True],
                   "clean_union": [False, True], "b_training_target": [np.nan, 1.0],
                   "_canonical_k_group": ["", "000002.SZ|K|20251001"],
                   "_repair_episode_group": ["", "REPAIR-1"]})
    frame = pd.DataFrame(values)
    split = {"train_mask": pd.Series([False, True], index=frame.index)}
    projection = study._feature_export_frame(frame, ["20251031", "20251103"], split)

    assert projection["trade_date"].tolist() == ["20251103"]
    assert projection["candidate_population"].tolist() == [True]
    assert set(study.F5_B_FEATURE_NAMES).issubset(projection.columns)
    assert not (set(study.F5_B_FEATURE_NAMES) & set(study.TARGET_COLUMNS))


def test_frozen_source_and_official_snapshot_gates_fail_closed():
    expected = act009.EXPECTED_BINDING
    source = {
        "generation_id": expected["generation_id"], "asof_date": expected["asof_date"],
        "identity": {"a_market_basis": {"price_basis": expected["price_basis"],
                                         "volume_basis": expected["volume_basis"]}},
        "backtest": {"panel_sha256": expected["anchor_sha256"],
                     "generation_manifest_sha256": expected["manifest_sha256"]},
    }
    assert act009._assert_bound_source(source) == expected
    source["generation_id"] = "different-generation"
    with pytest.raises(act009.Act009Error, match="BOUND_INPUT_MISMATCH"):
        act009._assert_bound_source(source)

    official = dict(act009.EXPECTED_OFFICIAL_TOP200)
    study._check_official_source(official)
    official["sha256"] = "different-sha"
    with pytest.raises(study.Act009BError, match="OFFICIAL_TOP200_BINDING_MISMATCH"):
        study._check_official_source(official)


def test_manifest_publishes_after_verified_train_oos_shards(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(study, "F5_B_FEATURE_NAMES", ())
    projection = pd.DataFrame({
        "trade_date": ["20260601", "20260901"], "ts_code": ["000001.SZ", "000002.SZ"],
        "union": [True, False], "v13_candidate_union": [False, True],
        "clean_union": [True, True], "clean_train_candidate": [True, False],
        "train_fit_mask": [True, False], "clean_oos_candidate": [False, True],
    })
    manifest = study._publish_dataset_manifest(
        projection, tmp_path, binding={"generation_id": "g"}, panel_source={"source": "v4"},
        official_meta={"sha256": "sha"}, market_dates=["20260601", "20260901"],
        study_dates=["20260601", "20260901"], split_guard={"post_purge_canonical_k_overlap": 0},
        f1_f4_meta={"f1_exact_rows": 1}, f5_meta={"fixed_block": "crowding>=500"},
    )
    path = tmp_path / "dataset_local_manifest.json"
    assert manifest["status"] == "READY_PREFIT"
    assert path.is_file()
    loaded = pd.read_json(path, typ="series")
    assert loaded["population"]["rows"] == 2
    assert loaded["population"]["train_rows"] == 1
    assert loaded["population"]["oos_rows"] == 1
    assert {item["split"] for item in loaded["shards"]} == {"train", "oos"}
