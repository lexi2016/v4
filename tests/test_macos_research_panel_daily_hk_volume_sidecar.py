from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


WORKTREE = Path(__file__).resolve().parents[1]
ACTIVE_PATCH_MANIFEST = WORKTREE / "tests/fixtures/d20_hk_uint32_active_reader.patch.json"
DATE = "20261120"
HK_DAY_STRUCT = struct.Struct("<IfffffII")
OVERFLOW_ROW = {
    "code": "HK.03033",
    "trade_date": DATE,
    "open": 123.45,
    "high": 127.89,
    "low": 120.12,
    "close": 125.67,
    "turnover": 9876543210.0,
    "volume": 6100000000,
    "source": "FUTU_HKCONNECT_SNAPSHOT",
    "name": "Synthetic HK test issue",
}
NORMAL_ROW = {
    "code": "HK.00001",
    "trade_date": DATE,
    "open": 10.0,
    "high": 11.0,
    "low": 9.0,
    "close": 10.5,
    "turnover": 1000.0,
    "volume": 2345,
    "source": "FUTU_HKCONNECT_SNAPSHOT",
}


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _make_package(name: str, directory: Path):
    package = types.ModuleType(name)
    package.__path__ = [str(directory)]
    sys.modules[name] = package
    return package


@pytest.fixture(scope="module")
def d20_modules():
    manifest = json.loads(ACTIVE_PATCH_MANIFEST.read_text(encoding="utf-8"))
    active_app = Path(
        os.environ.get("V4_D20_HK_ACTIVE_APP", str(WORKTREE))
    ).expanduser()
    active_reader_path = Path(
        os.environ.get(
            "V4_D20_HK_ACTIVE_READER",
            str(active_app / manifest["active_reader_relative_path"]),
        )
    ).expanduser()
    common_path = active_app / "ops" / "macos_research_panel_daily_common.py"
    if not common_path.is_file():
        pytest.skip(
            "exact split Main common module unavailable; set V4_D20_HK_ACTIVE_APP"
        )
    if not active_reader_path.is_file():
        pytest.skip(
            "exact active HK reader unavailable; set V4_D20_HK_ACTIVE_READER"
        )

    expected_base_sha = manifest["base_sha256"]
    base_bytes = active_reader_path.read_bytes()
    if hashlib.sha256(base_bytes).hexdigest() != expected_base_sha:
        pytest.skip("active HK reader SHA does not match frozen patch base")
    patch_path = WORKTREE / manifest["patch_path"]
    patch_bytes = patch_path.read_bytes()
    if hashlib.sha256(patch_bytes).hexdigest() != manifest["patch_sha256"]:
        pytest.skip("active HK reader patch SHA does not match manifest")

    package_name = "_d20_active_ops"
    _make_package(package_name, active_app / "ops")
    common = importlib.import_module(
        f"{package_name}.macos_research_panel_daily_common"
    )
    pack_name = f"{package_name}.macos_research_panel_daily_pack"
    pack = _load_module(
        pack_name, WORKTREE / "ops" / "macos_research_panel_daily_pack.py"
    )
    gate_name = f"{package_name}.macos_research_panel_daily_gate"
    gate = _load_module(
        gate_name, WORKTREE / "ops" / "macos_research_panel_daily_gate.py"
    )
    assert gate.pack_hk_day is pack.pack_hk_day

    candidate_reader_package = "_d20_candidate_shared_data"
    _make_package(
        candidate_reader_package,
        WORKTREE / "upstreams" / "v3_shared_data" / "shared_data",
    )
    reader_name = f"{candidate_reader_package}.hk_0_2"
    reader = importlib.import_module(reader_name)

    active_reader_package = "_d20_active_hk_reader"
    _make_package(active_reader_package, active_reader_path.parent)
    active_reader_name = f"{active_reader_package}.hk_0_2"
    active_reader = importlib.import_module(active_reader_name)

    module_name = f"{active_reader_package}.hk_0_2_d20_testpatch"
    overlay_root = None
    with tempfile.TemporaryDirectory(prefix="d20-hk-reader-overlay-") as temporary:
        overlay_root = Path(temporary)
        patched_path = Path(temporary) / "hk_0_2.py"
        shutil.copyfile(active_reader_path, patched_path)
        subprocess.run(
            ["git", "apply", "--check", "-p1", str(patch_path)],
            cwd=temporary,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "apply", "-p1", str(patch_path)],
            cwd=temporary,
            check=True,
            capture_output=True,
            text=True,
        )
        patched_bytes = patched_path.read_bytes()
        assert hashlib.sha256(patched_bytes).hexdigest() == manifest["patched_sha256"]
        patched_reader = _load_module(module_name, patched_path)
        try:
            yield SimpleNamespace(
                common=common,
                pack=pack,
                gate=gate,
                reader=reader,
                active_reader=active_reader,
                patched_reader=patched_reader,
                manifest=manifest,
            )
        finally:
            package_prefixes = (
                package_name,
                candidate_reader_package,
                active_reader_package,
            )
            for name in tuple(sys.modules):
                if any(
                    name == prefix or name.startswith(f"{prefix}.")
                    for prefix in package_prefixes
                ):
                    sys.modules.pop(name, None)
    assert overlay_root is not None and not overlay_root.exists()
    assert module_name not in sys.modules


def _rows():
    return [dict(NORMAL_ROW), dict(OVERFLOW_ROW)]


def _seed_prefix(root):
    day_root = root / "vipdoc" / "ds" / "lday"
    day_root.mkdir(parents=True)
    payload = HK_DAY_STRUCT.pack(20261119, 3.3, 3.5, 3.2, 3.4, 1000.0, 123, 0)
    (day_root / "71#03033.day").write_bytes(payload)
    return day_root, payload


def test_hk_volume_overflow_sidecar_preserves_full_row_and_reader_increment(
    tmp_path, d20_modules
):
    root = tmp_path / "tdx"
    day_root, prefix = _seed_prefix(root)
    capture_sha = "a" * 64
    raw_sha = "b" * 64

    packed = d20_modules.pack.pack_hk_day(
        root,
        _rows(),
        target_date=DATE,
        minimum_rows=2,
        expected_codes={"HK.00001", "HK.03033"},
        source_capture_sha256=capture_sha,
        source_capture_raw_sha256=raw_sha,
    )

    overflow_path = day_root / "71#03033.day"
    ledger_path = day_root / ".v4_hk_volume_overflow" / f"{DATE}.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    entry = ledger["rows"][0]
    assert overflow_path.read_bytes() == prefix
    assert entry["source_row"] == OVERFLOW_ROW
    assert entry["volume_shares"] == OVERFLOW_ROW["volume"]
    assert entry["volume_unit"] == "shares"
    assert entry["native_prefix"] == {
        "path": "71#03033.day",
        "size_bytes": len(prefix),
        "sha256": hashlib.sha256(prefix).hexdigest(),
    }
    normal_path = day_root / "71#00001.day"
    assert normal_path.read_bytes() == HK_DAY_STRUCT.pack(
        *d20_modules.pack._hk_record(NORMAL_ROW)
    )
    assert packed["row_count"] == 2
    assert {item["code"] for item in packed["files"]} == {
        "HK.00001",
        "HK.03033",
    }
    assert (
        next(item for item in packed["files"] if item["code"] == "HK.03033")[
            "storage"
        ]
        == "VOLUME_SIDECAR"
    )

    summary = d20_modules.pack.validate_hk_volume_sidecars(
        root,
        _rows(),
        target_date=DATE,
        source_capture_sha256=capture_sha,
        source_capture_raw_sha256=raw_sha,
    )
    assert summary["codes"] == ["HK.03033"]
    increment, source_count = d20_modules.reader._read_vipdoc_increment(
        day_root,
        after_date="20261119",
        through_date=DATE,
    )
    assert source_count == 2
    assert {row["code_norm"] for row in increment} == {
        "HK.00001",
        "HK.03033",
    }
    overflow = next(row for row in increment if row["code_norm"] == "HK.03033")
    assert overflow["trade_date_compact"] == DATE
    assert overflow["trade"] == OVERFLOW_ROW["volume"]
    assert overflow["amount"] == OVERFLOW_ROW["turnover"]
    assert overflow["source"] == "FUTU_HKCONNECT_SNAPSHOT_VOLUME_OVERFLOW"

    native_evidence = {}
    active_increment, active_file_count = (
        d20_modules.patched_reader._read_vipdoc_increment(
            day_root,
            after_date="20261119",
            through_date=DATE,
            evidence=native_evidence,
        )
    )
    assert len(active_increment) == 2
    assert active_file_count == 2
    assert native_evidence["fields"]["trade"]["storage_type"] == "uint32_le"
    assert len(native_evidence["source_files"]) == 1
    sidecar_observation = native_evidence["volume_overflow_sidecars"]
    assert len(sidecar_observation["source_files"]) == 1
    observed_sidecar = sidecar_observation["source_files"][0]
    assert observed_sidecar["sha256"] == hashlib.sha256(
        ledger_path.read_bytes()
    ).hexdigest()
    assert observed_sidecar["storage"] == "immutable_json_sidecar"
    assert observed_sidecar["volume_unit"] == "shares"
    assert (
        observed_sidecar["volume_source"]
        == "FUTU_HKCONNECT_SNAPSHOT.source_row.volume"
    )
    assert active_increment[-1]["trade"] == OVERFLOW_ROW["volume"]

    replay = d20_modules.pack.pack_hk_day(
        root,
        _rows(),
        target_date=DATE,
        minimum_rows=2,
        expected_codes={"HK.00001", "HK.03033"},
        source_capture_sha256="c" * 64,
        source_capture_raw_sha256="d" * 64,
    )
    assert replay["sha256"] == packed["sha256"]
    assert all(item["already_current"] for item in replay["files"])
    replayed_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert replayed_ledger["source_capture_sha256"] == capture_sha
    assert replayed_ledger["source_capture_raw_sha256"] == raw_sha


def test_hk_volume_sidecar_rejects_missing_or_changed_capture(tmp_path, d20_modules):
    root = tmp_path / "tdx"
    day_root, _ = _seed_prefix(root)
    with pytest.raises(d20_modules.common.SnapshotGateError, match="missing"):
        d20_modules.pack.validate_hk_volume_sidecars(
            root, _rows(), target_date=DATE
        )

    d20_modules.pack.pack_hk_day(
        root,
        _rows(),
        target_date=DATE,
        minimum_rows=2,
        expected_codes={"HK.00001", "HK.03033"},
        source_capture_sha256="a" * 64,
        source_capture_raw_sha256="b" * 64,
    )
    changed_rows = _rows()
    changed_rows[1]["close"] = 3.439
    with pytest.raises(
        d20_modules.common.SnapshotGateError,
        match="differs from capture",
    ):
        d20_modules.pack.validate_hk_volume_sidecars(
            root,
            changed_rows,
            target_date=DATE,
            source_capture_sha256="a" * 64,
            source_capture_raw_sha256="b" * 64,
        )

    ledger_path = day_root / ".v4_hk_volume_overflow" / f"{DATE}.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["rows"][0]["volume_shares"] += 1
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(
        d20_modules.patched_reader.StoreError,
        match="checksum mismatch",
    ):
        d20_modules.patched_reader._read_vipdoc_increment(
            day_root,
            after_date="20261119",
            through_date=DATE,
        )
