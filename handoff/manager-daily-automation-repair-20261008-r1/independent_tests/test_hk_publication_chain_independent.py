"""Independent offline probes for the actual HK child publication path.

The positive probe uses the exact 07aa child entry and original collector,
the real captured-membership V2 owner, actual security-master publisher and
readback, and actual chain receipt/readback. The Futu SDK returns synthetic
frames. At the frozen HK0.2 model boundary, the frozen model reader is replaced
with a strict panel-only fixture reader because the frozen model assets are
absent from this checkout, and the entry's `run_hk_0_2_authority` call is
replaced with a fixture writer that creates and binds a real parquet file,
manifest, and pointer; this does not exercise the frozen panel updater
algorithm. The TDX daily-supplement call is replaced with explicit
CANNOT_CONFIRM, so no supplement publication is claimed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

REVIEWER_DIR = Path(__file__).resolve().parent
if str(REVIEWER_DIR) not in sys.path:
    sys.path.insert(0, str(REVIEWER_DIR))
from _source_root import source_root  # noqa: E402

REPO = source_root(__file__)
for import_root in (REPO, REPO / "upstreams"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from infrastructure.owned_io import SafeRoot  # noqa: E402
from infrastructure import isolated_package_loader  # noqa: E402
from ops._macos_research_panel_daily_parts import hk_capture_gate as gate  # noqa: E402

HK = ZoneInfo("Asia/Hong_Kong")
FLAGS = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
ACTUAL_LAYER = REPO / "runtime_layers/hk_child/ops/macos_research_panel_daily.py"
UPDATER = REPO / "upstreams/v3_shared_data/scripts/update_hk_0_2_panel.py"


def _load_actual_layer():
    name = "reviewer_hk_actual_child_layer"
    module = sys.modules.get(name)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(name, ACTUAL_LAYER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sealed_decoy_chain(tmp_path: Path, target: str) -> tuple[Path, dict]:
    """Write READY stage names and one fake raw file, but no real chain roles."""
    chain_id, capture_run_id = "a" * 32, "d" * 32
    safe = SafeRoot(tmp_path)
    base = f"hk_publication/{target}/{chain_id}"
    safe.ensure_directory(base)
    refs = []
    for stage_name in gate.CHAIN_REQUIRED_STAGES:
        relative = f"{base}/{stage_name.lower()}.json"
        stage = gate._seal({
            "schema_version": gate.CHAIN_SCHEMA, "target_date": target,
            "chain_id": chain_id, "capture_run_id": capture_run_id,
            "stage": stage_name, "status": "READY",
            "started_at": "2026-10-08T01:00:00+00:00",
            "finished_at": "2026-10-08T01:00:01+00:00", **FLAGS,
        })
        raw = gate._canonical(stage) + b"\n"
        safe.write_bytes(relative, raw, require_absent=True)
        refs.append({"stage": stage_name, "path": relative,
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    decoy = tmp_path / "authority" / "capture.json"
    decoy.parent.mkdir(parents=True)
    decoy.write_bytes(b"synthetic immutable capture")
    terminal_relative = f"{base}/terminal.json"
    terminal = gate._seal({
        "schema_version": gate.CHAIN_SCHEMA, "status": "READY",
        "target_date": target, "chain_id": chain_id,
        "capture_run_id": capture_run_id,
        "started_at": "2026-10-08T01:00:00+00:00",
        "finished_at": "2026-10-08T01:01:00+00:00", "stages": refs,
        "artifact_refs": [{"path": str(decoy), "bytes": decoy.stat().st_size,
            "sha256": hashlib.sha256(decoy.read_bytes()).hexdigest(),
            "role": "HK_SDK_CAPTURE_RAW"}],
        "lane_summary": {"status": "READY", "target_date": target,
            "row_count": 600, "universe_count": 600, "coverage_rate": 1.0,
            "sha256": "b" * 64, "source_sha256": "c" * 64},
        "daily_supplement": {"status": "CANNOT_CONFIRM"}, **FLAGS,
    })
    terminal_raw = gate._canonical(terminal) + b"\n"
    safe.write_bytes(terminal_relative, terminal_raw, require_absent=True)
    pointer = gate._seal({
        "schema_version": gate.CHAIN_SCHEMA, "status": "READY",
        "target_date": target, "chain_id": chain_id,
        "terminal_relative": terminal_relative,
        "terminal_sha256": hashlib.sha256(terminal_raw).hexdigest(),
        "terminal_bytes": len(terminal_raw),
        "published_at": "2026-10-08T01:01:00+00:00", **FLAGS,
    })
    safe.write_bytes(f"hk_publication/{target}/latest.json",
        gate._canonical(pointer) + b"\n", require_absent=True)
    return decoy, pointer


def test_chain_reader_rejects_sealed_ready_stages_with_only_a_decoy_capture_ref(tmp_path):
    target = "20261008"
    _decoy, _pointer = _sealed_decoy_chain(tmp_path, target)
    actual = _load_actual_layer()

    with pytest.raises(ValueError):
        gate.read_verified_chain(actual.__dict__, tmp_path, target)


def test_failed_final_chain_readback_never_leaves_a_ready_latest_pointer(tmp_path, monkeypatch):
    """A final readback error must not promote or contradict a READY pointer."""
    target = datetime.now(HK).strftime("%Y%m%d")
    actual = _load_actual_layer()
    args = SimpleNamespace(receipt_root=tmp_path / "receipts",
        hk_asset_root=tmp_path / "store" / "assets" / "hk_0_2",
        hk_tdx_root=tmp_path / "tdx")
    monkeypatch.setattr(gate, "_today_shanghai", lambda: target)

    def ready_body(scope, *, target_date, capture_run_id, stage_start,
                   stage_finish, **_kwargs):
        scope["_LAST_HK_CAPTURE"] = {"capture_run_id": capture_run_id,
            "capture_sha256": "a" * 64, "target_date": target_date}
        for stage in gate.CHAIN_REQUIRED_STAGES:
            stage_start(stage)
            details = {"result": {}}
            if stage == "FINAL_READBACK":
                details = {"result": {"artifact_count": 0,
                    "publication_chain_status": "READY",
                    "lane_summary": {"status": "READY", "target_date": target_date,
                        "row_count": 1, "universe_count": 1, "coverage_rate": 1.0,
                        "sha256": "b" * 64, "source_sha256": "c" * 64,
                        "capture_run_id": capture_run_id,
                        "capture_sha256": "a" * 64,
                        "membership_run_id": "e" * 24,
                        "panel_sha256": "d" * 64,
                        "panel_capture_binding_sha256": "f" * 64,
                        "security_master_run_id": "1" * 24,
                        "security_master_artifact_sha256": "2" * 64}}}
            stage_finish(stage, "READY", **details)
        return {"status": "READY", "target_date": target_date,
            "row_count": 1, "universe_count": 1, "coverage_rate": 1.0,
            "sha256": "b" * 64, "source_sha256": "c" * 64,
            "membership": {}, "authority": {}, "security_master": {},
            "panel_capture_binding_sha256": "f" * 64,
            "capture_manifest_path": str(tmp_path / "unused-capture.json"),
            "capture_raw_path": str(tmp_path / "unused-raw.json")}

    monkeypatch.setattr(gate, "_run_hk_capture_gate_body", ready_body)
    monkeypatch.setattr(gate, "_artifact_refs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(gate, "_run_daily_supplement", lambda *_args, **_kwargs: {
        "status": "CANNOT_CONFIRM", "target_date": target,
        "reason_code": "SYNTHETIC_TEST_BOUNDARY",
    })
    reader_calls = 0

    def fail_the_final_readback(*_args, **_kwargs):
        nonlocal reader_calls
        reader_calls += 1
        if reader_calls == 1:  # no existing chain at admission
            return None
        raise ValueError("HK_PUBLICATION_CHAIN_READBACK_UNVERIFIED")

    monkeypatch.setattr(gate, "read_verified_chain", fail_the_final_readback)
    try:
        outcome = gate.run_hk_capture_gate(actual.__dict__, target_date=target,
            args=args, authority_paths={}, python_executable=Path(sys.executable))
    except Exception as error:
        pytest.fail(f"final verification failure escaped as {type(error).__name__}: {error}")

    latest = args.receipt_root / "hk_publication" / target / "latest.json"
    assert outcome.get("status") != "READY"
    if latest.exists():
        assert json.loads(latest.read_text(encoding="utf-8"))["status"] != "READY"


class _Frame:
    def __init__(self, rows):
        self.rows = list(rows)
        self.columns = list(self.rows[0]) if self.rows else []

    def to_dict(self, *, orient):
        assert orient == "records"
        return [dict(row) for row in self.rows]


class _SyntheticFutuContext:
    def __init__(self, target: str):
        self.target = target
        self.closed = False
        self.plate_calls = []
        self.snapshot_calls = []
        local_time = datetime.now(HK).strftime("%Y-%m-%d %H:%M:%S")
        self.codes = [f"HK.{index:05d}" for index in range(1, 701)]
        self.by_code = {
            code: {
                "code": code, "name": f"Synthetic {code[-5:]}",
                "update_time": local_time, "open_price": 10.0,
                "high_price": 10.5, "low_price": 9.5, "last_price": 10.2,
                "volume": 100000.0, "turnover": 1000000.0,
                "outstanding_shares": 1000000.0,
                "circular_market_val": 10000000.0,
                "listing_date": "2010-01-01", "lot_size": 100.0,
                "stock_owner": "Synthetic issuer", "stock_child_type": "EQUITY",
                "sec_status": "NORMAL",
            } for code in self.codes
        }

    def get_plate_stock(self, plate_code):
        self.plate_calls.append(plate_code)
        if plate_code == "HK.GangGuTong":
            codes = self.codes[:400]
        elif plate_code == "HK.LIST1922":
            codes = self.codes[300:]
        else:
            return 1, _Frame([])
        return 0, _Frame([{"code": code, "stock_name": self.by_code[code]["name"]}
            for code in codes])

    def get_market_snapshot(self, codes):
        self.snapshot_calls.append(tuple(codes))
        return 0, _Frame([self.by_code[code] for code in codes])

    def close(self):
        self.closed = True


class _SyntheticTwoDayFutuContext:
    def __init__(self, state):
        self.state = state
        self.closed = False
        self.codes = [f"HK.{index:05d}" for index in range(1, 601)]

    def get_plate_stock(self, plate_code):
        if plate_code not in {"HK.GangGuTong", "HK.LIST1922"}:
            return 1, _Frame([])
        return 0, _Frame([{"code": code, "stock_name": f"Synthetic issuer {code[-5:]}"}
            for code in self.codes])

    def get_market_snapshot(self, requested_codes):
        day = datetime.strptime(self.state["target"], "%Y%m%d")
        update_time = day.strftime("%Y-%m-%d") + " 17:20:00"
        return 0, _Frame([{
            "code": code, "name": f"Synthetic issuer {code[-5:]}",
            "update_time": update_time, "open_price": 10.0,
            "high_price": 11.0, "low_price": 9.0, "last_price": 10.0,
            "volume": 1000, "turnover": 10000.0,
            "outstanding_shares": 1000000, "circular_market_val": 10000000.0,
            "listing_date": "2010-01-01", "lot_size": 100,
            "stock_owner": "Synthetic owner", "stock_child_type": "Synthetic type",
            "sec_status": "NORMAL",
        } for code in requested_codes])

    def close(self):
        self.closed = True


def _write_panel_authority(asset_root: Path, target: str, codes: list[str]) -> dict:
    relative = f"panels/{target}-synthetic/panel.parquet"
    manifest_relative = f"panels/{target}-synthetic/manifest.json"
    panel_path = asset_root / relative
    panel_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "trade_date_compact": [target] * len(codes),
        "code_norm": codes,
        "close": [10.2] * len(codes),
    }).to_parquet(panel_path, index=False)
    panel_sha = hashlib.sha256(panel_path.read_bytes()).hexdigest()
    manifest = {
        "asset_schema_version": "v3_shared_data.hk_0_2_panel_asset.v2",
        "source_contract": "synthetic fixture at frozen HK0.2 model boundary",
        "panel_relative": relative, "panel_sha256": panel_sha,
        "panel_rows": len(codes), "panel_code_count": len(codes),
        "panel_max_date": target, "through_date_code_count": len(codes),
        "research_only": True,
        **FLAGS,
    }
    manifest_path = asset_root / manifest_relative
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    (asset_root / "panel_latest.json").write_text(
        json.dumps({"manifest_relative": manifest_relative}, sort_keys=True),
        encoding="utf-8",
    )
    return {"status": "READY", "target_date": target, "through_date": target,
        "through_date_code_count": len(codes), "panel_sha256": panel_sha,
        "manifest_relative": manifest_relative, "already_current": False, **FLAGS}


def test_actual_hk_child_uses_original_collector_v2_master_and_chain_readback(
        tmp_path, monkeypatch, capsys):
    target = datetime.now(HK).strftime("%Y%m%d")
    actual = _load_actual_layer()
    ensure = actual.importlib.import_module("ops.ensure_hk_security_master")
    context = _SyntheticFutuContext(target)
    futu = ModuleType("futu")
    futu.OpenQuoteContext = lambda **_kwargs: context
    monkeypatch.setitem(sys.modules, "futu", futu)

    def fake_model_reader(root):
        root = Path(root)
        pointer = json.loads((root / "panel_latest.json").read_text(encoding="utf-8"))
        manifest_path = (root / pointer["manifest_relative"]).resolve()
        manifest_path.relative_to(root.resolve())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        panel_path = (root / manifest["panel_relative"]).resolve()
        panel_path.relative_to(root.resolve())
        assert hashlib.sha256(panel_path.read_bytes()).hexdigest() == manifest["panel_sha256"]
        assert manifest["panel_max_date"] == target
        return SimpleNamespace(panel_manifest=manifest, panel_path=panel_path)

    original_loader = isolated_package_loader.load_isolated_package_module
    panel_reader = SimpleNamespace(load_frozen_hk_0_2_assets=fake_model_reader)

    def loader(package_root, *, package_directory, module_leaf, namespace_prefix):
        if package_directory == "shared_data" and module_leaf == "hk_0_2":
            return panel_reader
        return original_loader(package_root, package_directory=package_directory,
            module_leaf=module_leaf, namespace_prefix=namespace_prefix)

    monkeypatch.setattr(isolated_package_loader, "load_isolated_package_module", loader)
    panel_calls = []

    def panel_authority(_updater, _python, asset_root, _tdx_root, requested_target):
        assert requested_target == target
        panel_calls.append(target)
        return _write_panel_authority(Path(asset_root), target, context.codes)

    monkeypatch.setattr(actual, "run_hk_0_2_authority", panel_authority)
    monkeypatch.setattr(gate, "_run_daily_supplement", lambda *_args, **_kwargs: {
        "status": "CANNOT_CONFIRM", "target_date": target,
        "reason_code": "REVIEWER_SYNTHETIC_TDX_BOUNDARY_OMITTED",
    })

    receipt_root = tmp_path / "receipts"
    store_root = tmp_path / "store"
    asset_root = store_root / "assets" / "hk_0_2"
    tdx_root = tmp_path / "tdx"
    argv = ["--date", target, "--lane", "HK", "--receipt-root", str(receipt_root),
        "--hk-tdx-root", str(tdx_root), "--hk-updater-script", str(UPDATER),
        "--hk-python-executable", sys.executable, "--hk-asset-root", str(asset_root)]

    first_exit = actual.main(argv)
    json.loads(capsys.readouterr().out)  # bounded public envelope, distinct from full lane receipt
    first_lane = json.loads((receipt_root / f"hk-{target}.json").read_text(encoding="utf-8"))
    assert first_exit == 0, first_lane
    assert first_lane["status"] == "READY", first_lane
    assert first_lane["target_date"] == target
    assert first_lane["publication_chain"]["status"] == "VERIFIED"
    assert first_lane["security_master"]["security_master_readback_status"] == "VERIFIED"
    assert first_lane["daily_supplement"]["status"] == "CANNOT_CONFIRM"
    assert context.closed is True
    assert context.plate_calls == ["HK.GangGuTong", "HK.LIST1922"]
    assert len(context.snapshot_calls) == 4
    assert panel_calls == [target]


def test_day_one_chain_survives_day_two_latest_advance_and_still_rejects_immutable_tamper(
        tmp_path, monkeypatch, capsys):
    """A new day may advance shared latest pointers without invalidating yesterday."""
    d1, d2 = "20261008", "20261009"
    state = {"target": d1}
    actual = _load_actual_layer()
    package_root = REPO / "upstreams" / "v3_shared_data"
    updater = package_root / "scripts" / "update_hk_0_2_panel.py"
    monkeypatch.syspath_prepend(str(package_root))
    hk02 = importlib.import_module("shared_data.hk_0_2")
    ensure = importlib.import_module("ops.ensure_hk_security_master")
    capture_module = importlib.import_module("ops._macos_research_panel_daily_parts.hk_market_capture")
    codes = [f"HK.{number:05d}" for number in range(1, 601)]
    flags = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    store_root = tmp_path / "shared-data"
    asset_root = store_root / "assets" / "hk_0_2"
    asset_root.mkdir(parents=True)
    tdx_root = tmp_path / "tdx"
    seed_panel = tmp_path / "seed-panel.parquet"
    pd.DataFrame([{"trade_date_compact": "20261007", "code_norm": code,
        "close": 10.0} for code in codes]).to_parquet(seed_panel, index=False)
    seed_manifest = {"panel_sha256": hashlib.sha256(seed_panel.read_bytes()).hexdigest(),
        "panel_max_date": "20261007", "through_date_code_count": len(codes)}

    def read_published_panel(root):
        root = Path(root).resolve()
        pointer = json.loads((root / "panel_latest.json").read_text(encoding="utf-8"))
        manifest_path = (root / pointer["manifest_relative"]).resolve()
        manifest_path.relative_to(root)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        panel_path = (root / manifest["panel_relative"]).resolve()
        panel_path.relative_to(root)
        assert hashlib.sha256(panel_path.read_bytes()).hexdigest() == manifest["panel_sha256"]
        return SimpleNamespace(panel_manifest=manifest, panel_path=panel_path)

    monkeypatch.setattr(hk02, "load_frozen_hk_0_2_assets",
        lambda root: read_published_panel(root) if (Path(root) / "panel_latest.json").exists()
        else SimpleNamespace(panel_path=seed_panel, panel_manifest=seed_manifest))

    class FrozenShanghaiClock(datetime):
        @classmethod
        def now(cls, tz=None):
            day = datetime.strptime(state["target"], "%Y%m%d")
            fixed = datetime(day.year, day.month, day.day, 17, 20, tzinfo=HK)
            return fixed.astimezone(tz) if tz is not None else fixed

    monkeypatch.setattr(ensure, "datetime", FrozenShanghaiClock)
    monkeypatch.setattr(gate, "_today_shanghai", lambda: state["target"])
    monkeypatch.setattr(actual, "_today_shanghai", lambda: state["target"])
    monkeypatch.setattr(capture_module, "_utc_now_iso", lambda:
        datetime.strptime(state["target"], "%Y%m%d").replace(tzinfo=HK)
        .replace(hour=17, minute=20).astimezone(timezone.utc).isoformat())

    contexts = []
    futu = ModuleType("futu")
    futu.OpenQuoteContext = lambda **_kwargs: contexts.append(_SyntheticTwoDayFutuContext(state)) or contexts[-1]
    monkeypatch.setitem(sys.modules, "futu", futu)
    def publish_panel_with_original_updater(updater_path, python, assets, tdx, target):
        result = hk02.update_hk_0_2_panel_from_vipdoc(assets, tdx_root=tdx, through_date=target)
        return {**result, "target_date": target,
            "argv": [str(python), str(updater_path), "--asset-root", str(assets),
                     "--tdx-root", str(tdx), "--through-date", target], **flags}
    monkeypatch.setattr(actual, "run_hk_0_2_authority", publish_panel_with_original_updater)
    def read_frozen_panel(root):
        return read_published_panel(root)
    original_loader = importlib.import_module("infrastructure.isolated_package_loader").load_isolated_package_module
    panel_reader = SimpleNamespace(load_frozen_hk_0_2_assets=read_frozen_panel)
    def isolated_loader(root, *, package_directory, module_leaf, namespace_prefix):
        if package_directory == "shared_data" and module_leaf == "hk_0_2":
            return panel_reader
        return original_loader(root, package_directory=package_directory,
            module_leaf=module_leaf, namespace_prefix=namespace_prefix)
    monkeypatch.setattr(importlib.import_module("infrastructure.isolated_package_loader"),
        "load_isolated_package_module", isolated_loader)
    monkeypatch.setattr(gate, "_run_daily_supplement", lambda *_args, **_kwargs: {
        "status": "CANNOT_CONFIRM", "target_date": state["target"],
        "reason_code": "REVIEWER_SYNTHETIC_TDX_DAILY_SUPPLEMENT_BOUNDARY", **flags})

    receipt_root = tmp_path / "receipts"
    def args_for(day):
        return ["--date", day, "--lane", "HK", "--receipt-root", str(receipt_root),
            "--hk-tdx-root", str(tdx_root), "--hk-updater-script", str(updater),
            "--hk-python-executable", sys.executable, "--hk-asset-root", str(asset_root)]

    assert actual.main(args_for(d1)) == 0
    capsys.readouterr()
    first_lane = json.loads((receipt_root / f"hk-{d1}.json").read_text(encoding="utf-8"))
    first = gate.read_verified_chain(actual.__dict__, receipt_root, d1)
    assert first_lane["status"] == "READY" and first is not None
    first_terminal_raw = (receipt_root / first["terminal_relative"]).read_bytes()
    mutable_roles = {"HK_PANEL_LATEST_POINTER", "HK_SECURITY_MASTER_LATEST_POINTER"}
    immutable_paths = {reference["path"] for reference in first["terminal"]["artifact_refs"]
        if reference["role"] not in mutable_roles}
    immutable_paths.add(str((receipt_root / first["terminal_relative"]).resolve()))
    immutable_paths.update(str((receipt_root / reference["path"]).resolve())
        for reference in first["terminal"]["stages"])
    immutable_before = {path: Path(path).read_bytes() for path in sorted(immutable_paths)}
    panel_pointer_path = asset_root / "panel_latest.json"
    master_pointer_path = store_root / "assets" / "hk_security_master" / "latest.json"
    panel_pointer_d1 = panel_pointer_path.read_bytes()
    master_pointer_d1 = master_pointer_path.read_bytes()
    from upstreams.v3_shared_data.shared_data.hk_security_master import load_verified_hk_security_master
    old_master_rows, old_master_manifest = load_verified_hk_security_master(store_root, d1)
    assert len(old_master_rows) == len(codes)

    state["target"] = d2
    assert actual.main(args_for(d2)) == 0
    capsys.readouterr()
    second_lane = json.loads((receipt_root / f"hk-{d2}.json").read_text(encoding="utf-8"))
    second = gate.read_verified_chain(actual.__dict__, receipt_root, d2)
    assert second_lane["status"] == "READY" and second is not None
    assert panel_pointer_path.read_bytes() != panel_pointer_d1
    assert master_pointer_path.read_bytes() != master_pointer_d1
    assert immutable_before == {path: Path(path).read_bytes() for path in sorted(immutable_paths)}
    still_old_rows, still_old_manifest = load_verified_hk_security_master(store_root, d1)
    assert still_old_rows == old_master_rows
    assert still_old_manifest["run_id"] == old_master_manifest["run_id"]
    assert still_old_manifest["artifact_sha256"] == old_master_manifest["artifact_sha256"]

    # This is the new two-date contract: D1 remains a verifiable cache after
    # independent original D2 publishers move the shared latest pointers.
    first_after_d2 = gate.read_verified_chain(actual.__dict__, receipt_root, d1)
    assert first_after_d2 is not None
    assert first_after_d2["terminal"]["chain_id"] == first["terminal"]["chain_id"]
    assert first_after_d2["terminal_sha256"] == first["terminal_sha256"]
    assert actual._hk_lane_receipt_ready(receipt_root, d1, first_lane) is True
    assert actual.main(args_for(d1)) == 0
    capsys.readouterr()
    cached_d1 = json.loads((receipt_root / f"hk-{d1}.json").read_text(encoding="utf-8"))
    assert cached_d1["cache_hit"] is True
    assert len(contexts) == 2 and all(context.closed for context in contexts)

    # Mutable current pointers are expected to advance; immutable D1 evidence
    # remains pinned to D1 bytes and still rejects a real old-artifact change.
    published = next(reference for reference in first["terminal"]["artifact_refs"]
        if reference["role"] == "HK_CONNECT_V2_PUBLICATION")
    tampered_path = Path(published["path"])
    original_bytes = tampered_path.read_bytes()
    tampered_path.write_bytes(b"x" + original_bytes[1:])
    with pytest.raises(ValueError, match="HK_PUBLICATION_CHAIN_ARTIFACT_SHA_MISMATCH"):
        gate.read_verified_chain(actual.__dict__, receipt_root, d1)
    assert actual._hk_lane_receipt_ready(receipt_root, d1, first_lane) is False

