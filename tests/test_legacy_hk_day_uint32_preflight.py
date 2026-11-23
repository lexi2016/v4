from __future__ import annotations

import json
import os
import struct
import sys
import types
from pathlib import Path

import pytest

from ops.prepare_legacy_hk_day_overlay import LEGACY_PANEL_PATH, render_legacy_hk_day_module


DATE = "20261123"
PREVIOUS = "20261120"
RAW_D23_VOLUME = 5_645_792_859
UINT32_MAX = (1 << 32) - 1
ABI = struct.Struct("<IfffffII")
LOCAL_LEGACY_APP = (
    Path.home() / "Library/Application Support/com.lexi.v4.local/releases"
    / "v4-retirement-20261028-hk-child/app"
)


@pytest.fixture(scope="module")
def preimage():
    path = Path(os.environ.get("V4_B4_LEGACY_HK_APP", LOCAL_LEGACY_APP)) / LEGACY_PANEL_PATH
    if not path.is_file():
        pytest.skip("exact legacy HK role preimage unavailable")
    return path.read_bytes()


def legacy_module(source):
    module = types.ModuleType("b4_exact_legacy_hk_child")
    module.__file__ = str(LOCAL_LEGACY_APP / LEGACY_PANEL_PATH)
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


@pytest.fixture
def candidate(preimage):
    return legacy_module(render_legacy_hk_day_module(preimage))


def row(code, volume, date=DATE, **overrides):
    return dict(
        trade_date=date, code=code, source="FUTU_HKCONNECT_SNAPSHOT",
        name=f"Test {code[3:]}", open=10.0, high=10.5, low=9.5, close=10.0,
        turnover=200_000.0, volume=volume,
    ) | overrides


def day_path(root, code):
    return root / "vipdoc" / "ds" / "lday" / f"71#{code}.day"


def seed(root, code, *dates):
    path = day_path(root, code)
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = b"".join(ABI.pack(int(date), 10, 10.5, 9.5, 10, 200_000, 1, 0) for date in dates)
    path.write_bytes(previous)
    return previous


def market_rows(count):
    rows = [row(f"HK.{index:05d}", 1_000) for index in range(1, count)]
    rows[0]["volume"] = UINT32_MAX
    rows.append(row("HK.03033", RAW_D23_VOLUME))
    return rows


class SnapshotFixture:
    def __init__(self, rows):
        self.rows = {value["code"]: value for value in rows}
        self.closed = False

    def get_plate_stock(self, plate):
        assert plate in {"HK.GangGuTong", "HK.LIST1922"}
        return 0, [{"code": code, "name": value["name"]} for code, value in self.rows.items()]

    def get_market_snapshot(self, codes):
        return 0, [self._snapshot(self.rows[code]) for code in codes]

    def close(self):
        self.closed = True

    @staticmethod
    def _snapshot(value):
        return {
            "code": value["code"], "name": value["name"], "update_time": "2026-11-23 16:08:04",
            "open_price": value["open"], "high_price": value["high"], "low_price": value["low"],
            "last_price": value["close"], "volume": value["volume"], "turnover": value["turnover"],
        }


def test_old_uint32_error_and_partial_write_on_same_d_raw_witness(preimage, tmp_path):
    original = legacy_module(preimage)
    prior = seed(tmp_path, "03033", PREVIOUS)
    with pytest.raises(struct.error, match=r"'I' format requires 0 <= number <= 4294967295"):
        original.pack_hk_day(
            tmp_path,
            [row("HK.03032", UINT32_MAX), row("HK.03033", RAW_D23_VOLUME)],
            target_date=DATE, minimum_rows=2,
        )
    assert ABI.unpack(day_path(tmp_path, "03032").read_bytes())[6] == UINT32_MAX
    assert day_path(tmp_path, "03033").read_bytes() == prior


def test_mixed_pack_preserves_bytes_exact_values_and_idempotent_retry(candidate, tmp_path):
    histories = {code: seed(tmp_path, code, PREVIOUS) for code in ("03032", "03033")}
    rows = [row("HK.03032", UINT32_MAX), row("HK.03033", RAW_D23_VOLUME), row("HK.03034", 0)]
    kwargs = dict(target_date=DATE, minimum_rows=2, expected_codes={value["code"] for value in rows})
    packed = candidate.pack_hk_day(tmp_path, rows, **kwargs)
    assert packed["status"] == "READY"
    assert packed["packed_codes"] == ["HK.03032", "HK.03034"]
    assert packed["coverage_rate"] == 2 / 3
    assert packed["quarantine"] == [{
        "code": "HK.03033", "trade_date": DATE, "source": "FUTU_HKCONNECT_SNAPSHOT",
        "source_field": "volume", "raw_value": RAW_D23_VOLUME, "unit": "shares",
        "destination_field": "trade_v", "destination_type": "uint32_le", "byte_offset": 24,
        "minimum": 0, "maximum": UINT32_MAX, "reason": "HK_DAY_UINT32_VOLUME_OUT_OF_RANGE",
    }]
    accepted = day_path(tmp_path, "03032").read_bytes()
    assert accepted[:ABI.size] == histories["03032"]
    assert ABI.unpack(accepted[ABI.size:]) == (int(DATE), 10, 10.5, 9.5, 10, 200_000, UINT32_MAX, 0)
    assert ABI.unpack(day_path(tmp_path, "03034").read_bytes())[6] == 0
    assert day_path(tmp_path, "03033").read_bytes() == histories["03033"]
    retry = candidate.pack_hk_day(tmp_path, rows, **kwargs)
    assert retry["sha256"] == packed["sha256"]
    assert all(item["already_current"] for item in retry["files"])


@pytest.mark.parametrize(
    ("rows", "expected", "reason"),
    [
        ([row("HK.03032", 1), row("HK.03033", 1, PREVIOUS)], None, "exact target date mismatch"),
        ([row("HK.03032", 1), row("03032.HK", 1)], None, "duplicate code"),
        ([row("HK.03032", 1), row("SZ.03033", RAW_D23_VOLUME)], None, "invalid security identity"),
        ([row("HK.03032", 1), row("HK.03033", 1)], {"HK.03032", "HK.03034"}, "coverage mismatch"),
        ([row("HK.03032", 1), row("HK.03033", RAW_D23_VOLUME, turnover=1e80)], None, "non-volume .day"),
        ([row("HK.03032", 1), row("HK.03033", 1.25)], None, "not a finite integer"),
    ],
)
def test_unattributable_errors_fail_with_no_writes(candidate, tmp_path, rows, expected, reason):
    with pytest.raises(candidate.SnapshotGateError, match=reason):
        candidate.pack_hk_day(tmp_path, rows, target_date=DATE, minimum_rows=1, expected_codes=expected)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(("conflict_code", "existing_date"), [("03033", DATE), ("99998", DATE), ("03032", "20261124")])
def test_conflicting_ambient_day_is_never_ingested_or_rewritten(candidate, tmp_path, conflict_code, existing_date):
    previous = seed(tmp_path, conflict_code, PREVIOUS, existing_date)
    with pytest.raises(candidate.SnapshotGateError, match="target.date"):
        candidate.pack_hk_day(
            tmp_path, [row("HK.03031", 1), row("HK.03032", 1), row("HK.03033", RAW_D23_VOLUME)],
            target_date=DATE, minimum_rows=2,
        )
    assert list(tmp_path.rglob("*.day")) == [day_path(tmp_path, conflict_code)]
    assert day_path(tmp_path, conflict_code).read_bytes() == previous


def test_legacy_entrypoint_reports_insufficient_coverage_and_writes_no_days(candidate, tmp_path, monkeypatch):
    context = SnapshotFixture(market_rows(600))
    monkeypatch.setitem(sys.modules, "futu", types.SimpleNamespace(OpenQuoteContext=lambda **_: context))
    monkeypatch.setattr(
        candidate, "run_hk_0_2_authority",
        lambda *args: pytest.fail("authority called after failed preflight"),
    )
    preserved = seed(tmp_path / "tdx", "03033", PREVIOUS)
    assert candidate.main([
        "--date", DATE, "--lane", "HK", "--receipt-root", str(tmp_path / "receipts"),
        "--hk-tdx-root", str(tmp_path / "tdx"), "--hk-asset-root", str(tmp_path / "assets"),
        "--hk-updater-script", str(tmp_path / "updater.py"),
    ]) == 1
    receipt = json.loads((tmp_path / "receipts" / f"hk-{DATE}.json").read_bytes())
    assert receipt["status"] == "FAILED"
    assert "post-quarantine minimum coverage requires 600 rows, got 599" in receipt["error"]
    evidence = receipt["hk_pack_preflight"]
    assert evidence["expected_code_count"] == 600 and evidence["packable_code_count"] == 599
    assert evidence["packed_code_count"] == evidence["new_day_write_count"] == 0
    assert evidence["quarantine"][0]["raw_value"] == RAW_D23_VOLUME
    assert context.closed
    assert list((tmp_path / "tdx").rglob("*.day")) == [day_path(tmp_path / "tdx", "03033")]
    assert day_path(tmp_path / "tdx", "03033").read_bytes() == preserved
    assert not (tmp_path / "assets").exists()
    assert not (tmp_path / "receipts" / f"a-{DATE}.json").exists()


def test_overlay_rejects_modified_legacy_preimage(preimage):
    with pytest.raises(ValueError, match="preimage SHA mismatch"):
        render_legacy_hk_day_module(preimage + b"\n")
