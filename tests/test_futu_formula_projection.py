from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = REPO_ROOT / "upstreams/v3_shared_data/shared_data/futu_formula_projection.py"
SPEC = importlib.util.spec_from_file_location("futu_formula_projection_test", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
projection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(projection)


def _json_sha256(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_profile(root: Path, *, factor_symbols=None) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    source_path = root / "source.parquet"
    source = pd.DataFrame({"ts_code": ["600000.SH"], "trade_date": ["20261023"], "close": [10.0]})
    source.to_parquet(source_path, index=False)
    cache_path = root / projection.CACHE_FILE
    cache = pd.DataFrame(
        [
            {"ts_code": "600000.SH", "trade_date": "20261022", "open": 9.0, "high": 10.0, "low": 8.0, "close": 9.5,
             "BBI": 9.1, "zge_white_line": 9.2, "zge_yellow_line": 9.3, "ma60": 9.4},
            {"ts_code": "600000.SH", "trade_date": "20261023", "open": 9.5, "high": 11.0, "low": 9.0, "close": 10.5,
             "BBI": 10.1, "zge_white_line": 10.2, "zge_yellow_line": 10.3, "ma60": 10.4},
        ]
    )
    cache.to_parquet(cache_path, index=False)
    if factor_symbols is None:
        factor_symbols = {
            "600000.SH": {
                "source_csv_path": "fixture.csv",
                "source_csv_sha256": "a" * 64,
                "events": [{"ex_div_date": "20260630", "factor_a": "1.0", "factor_b": "-0.4"}],
            }
        }
    factor_metadata = {
        "source": "Futu OpenD get_rehab quote-only cross-check",
        "source_capture_sha256": "b" * 64,
        "asof_cutoff": "20261023",
        "symbols": factor_symbols,
    }
    profile = {
        "schema": projection.PROFILE_SCHEMA,
        "profile_id": projection.PROFILE_ID,
        "chart_only": True,
        "historical_pit_certified": False,
        "asof_date": "20261023",
        "factor_basis": "FUTU_GET_REHAB_FORWARD_FACTOR_A_B",
        "factor_observed_at": "2026-10-24T12:48:57+08:00",
        "factor_source_csv_sha256": {"600000.SH": "a" * 64},
        "factor_metadata": factor_metadata,
        "factor_metadata_sha256": _json_sha256(factor_metadata),
        "source_panel_path": str(source_path.resolve()),
        "source_panel_sha256": projection.sha256_file(source_path),
        "source_panel_asof": "20261023",
        "formula_source_sha256": projection.PINNED_FORMULA_SHA256,
        "user_formula_sha256": projection.PINNED_USER_FORMULA_SHA256,
        "derived_cache_file": projection.CACHE_FILE,
        "derived_cache_sha256": projection.sha256_file(cache_path),
        "supported_columns": list(projection.PROFILE_SUPPORTED_COLUMNS),
    }
    profile["manifest_sha256"] = _json_sha256(profile)
    profile_path = root / projection.PROFILE_FILE
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return source_path, profile_path


def _refresh_manifest(profile_path: Path, *, refresh_factor_hash=False) -> None:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if refresh_factor_hash:
        profile["factor_metadata_sha256"] = _json_sha256(profile["factor_metadata"])
    profile.pop("manifest_sha256", None)
    profile["manifest_sha256"] = _json_sha256(profile)
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def test_futu_forward_factors_sort_events_and_respect_ex_date_boundary():
    bars = pd.DataFrame(
        {
            "trade_date": ["20260525", "20260526", "20260527", "20260601", "20260602"],
            "open": [10.0, 20.0, 30.0, 40.0, 50.0],
            "high": [10.0, 20.0, 30.0, 40.0, 50.0],
            "low": [10.0, 20.0, 30.0, 40.0, 50.0],
            "close": [10.0, 20.0, 30.0, 40.0, 50.0],
        }
    )
    events = [
        {"ex_div_date": "20260601", "factor_a": "0.5", "factor_b": "1.05"},
        {"ex_div_date": "20260526", "factor_a": "1.0", "factor_b": "-1.2"},
    ]
    result = projection.apply_forward_factors(bars, events, "20260602")
    assert result["trade_date"].tolist() == ["20260525", "20260526", "20260527", "20260601", "20260602"]
    assert result["close"].tolist() == [5.45, 11.05, 16.05, 40.0, 50.0]
    assert result["open"].tolist() == result["close"].tolist()


def test_futu_forward_factors_drop_future_rows_and_events():
    bars = pd.DataFrame(
        {"trade_date": ["20260525", "20260526", "20260601"],
         "open": [10.0, 20.0, 40.0], "high": [10.0, 20.0, 40.0],
         "low": [10.0, 20.0, 40.0], "close": [10.0, 20.0, 40.0]}
    )
    events = [
        {"ex_div_date": "20260526", "factor_a": "1.0", "factor_b": "-1.2"},
        {"ex_div_date": "20260601", "factor_a": "0.5", "factor_b": "1.05"},
    ]
    result = projection.apply_forward_factors(bars, events, "20260531")
    assert result["trade_date"].tolist() == ["20260525", "20260526"]
    assert result["close"].tolist() == [8.8, 20.0]


def test_profile_metadata_binds_factor_source_and_source_panel(tmp_path):
    source_path, _ = _write_profile(tmp_path)
    bound = projection.validate_profile(tmp_path, source_path, "20261023")
    assert bound["source_panel_sha256"] == projection.sha256_file(source_path)
    assert projection.profile_metadata(bound)["price_basis"] == "FUTU_QFQ_ASOF"
    assert projection.profile_metadata(bound)["historical_pit_certified"] is False
    assert projection.profile_metadata(bound)["factor_source_csv_sha256"] == {"600000.SH": "a" * 64}
    assert projection.profile_metadata(bound)["factor_source_csv_paths"] == {"600000.SH": "fixture.csv"}
    frame = projection.load_profile_rows(bound, ts_codes=["600000.SH"])
    assert frame.columns.tolist() == ["ts_code", "trade_date", *projection.PROFILE_SUPPORTED_COLUMNS]
    assert frame["trade_date"].max() == "20261023"
    assert frame.attrs["profile_metadata"]["source_panel_sha256"] == bound["source_panel_sha256"]


def test_future_profile_asof_fails_closed(tmp_path):
    source_path, _ = _write_profile(tmp_path)
    with pytest.raises(projection.FutuProfileError, match="FUTU_PROFILE_FUTURE_ASOF"):
        projection.validate_profile(tmp_path, source_path, "20261024")


def test_factor_metadata_hash_conflict_fails_closed(tmp_path):
    source_path, profile_path = _write_profile(tmp_path)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["factor_metadata"]["symbols"]["600000.SH"]["events"][0]["factor_b"] = "-0.5"
    profile.pop("manifest_sha256")
    profile["manifest_sha256"] = _json_sha256(profile)
    profile_path.write_text(json.dumps(profile, sort_keys=True), encoding="utf-8")
    with pytest.raises(projection.FutuProfileError, match="FACTOR_METADATA_SHA256_MISMATCH"):
        projection.validate_profile(tmp_path, source_path, "20261023")


def test_factor_csv_hash_and_cache_filename_must_match_manifest(tmp_path):
    source_path, profile_path = _write_profile(tmp_path)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["factor_source_csv_sha256"]["600000.SH"] = "c" * 64
    profile.pop("manifest_sha256")
    profile["manifest_sha256"] = _json_sha256(profile)
    profile_path.write_text(json.dumps(profile, sort_keys=True), encoding="utf-8")
    with pytest.raises(projection.FutuProfileError, match="FUTU_FACTOR_SOURCE_HASH_MISMATCH"):
        projection.validate_profile(tmp_path, source_path, "20261023")

    source_path, profile_path = _write_profile(tmp_path / "cache-name")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["derived_cache_file"] = "another_cache.parquet"
    profile.pop("manifest_sha256")
    profile["manifest_sha256"] = _json_sha256(profile)
    profile_path.write_text(json.dumps(profile, sort_keys=True), encoding="utf-8")
    with pytest.raises(projection.FutuProfileError, match="DERIVED_CACHE_FILE_MISMATCH"):
        projection.validate_profile(tmp_path / "cache-name", source_path, "20261023")


def test_missing_factor_coverage_fails_closed(tmp_path):
    source_path, _ = _write_profile(tmp_path)
    bound = projection.validate_profile(tmp_path, source_path, "20261023")
    with pytest.raises(projection.FutuProfileError, match="MISSING_FACTOR_COVERAGE"):
        projection.load_profile_rows(bound, ts_codes=["002612.SZ"])


def test_missing_events_and_bad_cache_or_panel_hash_fail_closed(tmp_path):
    source_path, _ = _write_profile(
        tmp_path / "missing-events",
        factor_symbols={
            "600000.SH": {
                "source_csv_path": "fixture.csv",
                "source_csv_sha256": "a" * 64,
                "events": [],
            }
        },
    )
    with pytest.raises(projection.FutuProfileError, match="MISSING_FACTOR_EVENTS"):
        projection.validate_profile(tmp_path / "missing-events", source_path, "20261023")

    # Restore a valid profile, then independently corrupt each immutable input.
    source_path, profile_path = _write_profile(tmp_path / "fresh")
    cache_path = tmp_path / "fresh" / projection.CACHE_FILE
    source_path.write_bytes(source_path.read_bytes() + b"corrupt")
    projection._FILE_HASH_CACHE.clear()
    with pytest.raises(projection.FutuProfileError, match="SOURCE_PANEL_SHA256_MISMATCH"):
        projection.validate_profile(tmp_path / "fresh", source_path, "20261023")

    source_path, profile_path = _write_profile(tmp_path / "cache")
    cache_path = tmp_path / "cache" / projection.CACHE_FILE
    cache_path.write_bytes(cache_path.read_bytes() + b"corrupt")
    projection._FILE_HASH_CACHE.clear()
    with pytest.raises(projection.FutuProfileError, match="DERIVED_CACHE_SHA256_MISMATCH"):
        projection.validate_profile(tmp_path / "cache", source_path, "20261023")


def test_asof_row_must_exist_even_when_requested_window_is_older(tmp_path):
    source_path, profile_path = _write_profile(tmp_path)
    cache_path = tmp_path / projection.CACHE_FILE
    cache = pd.read_parquet(cache_path)
    cache = cache[cache["trade_date"].ne("20261023")]
    cache.to_parquet(cache_path, index=False)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["derived_cache_sha256"] = projection.sha256_file(cache_path)
    profile.pop("manifest_sha256", None)
    profile["manifest_sha256"] = _json_sha256(profile)
    profile_path.write_text(json.dumps(profile, sort_keys=True), encoding="utf-8")
    projection._FILE_HASH_CACHE.clear()
    bound = projection.validate_profile(tmp_path, source_path, "20261023")
    with pytest.raises(projection.FutuProfileError, match="STALE_OR_MISSING_ASOF"):
        projection.load_profile_rows(bound, ts_codes=["600000.SH"], start_date="20261020", end_date="20261022")
