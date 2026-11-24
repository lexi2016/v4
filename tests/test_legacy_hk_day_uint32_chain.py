"""Opt-in isolation of the exact runtime owners with synthetic market rows."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import pytest

from ops.prepare_legacy_hk_day_overlay import (
    HK_UPDATER_PATH, LEGACY_PANEL_PATH, render_legacy_hk_day_module,
    render_legacy_hk_updater_module,
)
from test_hk_history_resolution import install_resolution
from test_legacy_hk_day_uint32_preflight import (
    ABI, DATE, LOCAL_LEGACY_APP, PREVIOUS, RAW_D23_VOLUME, SnapshotFixture, day_path, market_rows, seed,
)


NEXT = "20261124"
LOCAL = Path.home() / "Library/Application Support/com.lexi.v4.local"
ACTIVE_MAIN = LOCAL / "candidates/v4-main-plan2-p0-20261123-r4/app"
HK_UPDATER_ROLE_ROOTS = {
    "child-updater": LOCAL / "releases/workbench-daily-chain-20261031-r6-main/app/components/hk_updater",
    "shared-updater": LOCAL / "candidates/v4-v192-source-binding-20261112-r3/shared-package",
}
HK_PYTHON = LOCAL / "runtime/retirement-main-20261028/venvs/v4-hk02/bin/python"
RUN_OWNER_CHAIN = os.environ.get("V4_B4_HK_OWNER_CHAIN") == "1"
HK_ASSETS = (
    Path.home() / "Library/Application Support/com.lexi.v35.local/state/workspace"
    / "v3_shared_data/.runtime/data/assets/hk_0_2"
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def run_json(args, *, cwd, pythonpath="", expected_exit=0):
    env = {
        "PATH": os.defpath, "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(pythonpath), "OPENBLAS_NUM_THREADS": "2",
    }
    process = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=60)
    assert process.returncode == expected_exit, (args, process.stdout[-3500:], process.stderr[-3500:])
    return json.loads(process.stdout.strip().splitlines()[-1])


def stage_updater(root, role):
    source = HK_UPDATER_ROLE_ROOTS[role]
    patched = render_legacy_hk_updater_module((source / HK_UPDATER_PATH).read_bytes(), role=role)
    for relative in ("shared_data", "scripts"):
        shutil.copytree(source / relative, root / relative, ignore=shutil.ignore_patterns("__pycache__"))
    (root / HK_UPDATER_PATH).write_bytes(patched)
    return root


def create_seed(asset_root, codes, *, through_date=PREVIOUS):
    asset_root.mkdir(parents=True)
    model_pointer = json.loads((HK_ASSETS / "model_latest.json").read_bytes())
    model_manifest_path = HK_ASSETS / model_pointer["manifest_relative"]
    model_manifest = json.loads(model_manifest_path.read_bytes())
    model_relative = Path(model_manifest["bundle_relative"])
    (asset_root / model_relative).parent.mkdir(parents=True)
    # Copy only the immutable model into the temporary isolated owner scope.
    shutil.copyfile(HK_ASSETS / model_relative, asset_root / model_relative)
    shutil.copyfile(model_manifest_path, asset_root / model_pointer["manifest_relative"])
    write_json(asset_root / "model_latest.json", model_pointer)

    seed_rows = []
    for code in codes:
        for date, close, pre_close in zip(
            ("20261117", "20261118", "20261119", PREVIOUS),
            (8.8, 9.2, 9.6, 10.0),
            (8.45, 8.8, 9.2, 9.6),
            strict=True,
        ):
            if date > through_date:
                continue
            seed_rows.append({
                "trade_date": int(date), "trade_date_compact": date,
                "code_norm": code, "name": f"Test {code[3:]}",
                "open": pre_close, "high": close * 1.01, "low": pre_close * 0.995,
                "close": close, "pre_close": pre_close, "amount": 100_000.0, "trade": 900,
                "continuity_segment_id": 1,
            })
    panel = asset_root / "fixture_seed.parquet"
    pd.DataFrame(seed_rows).to_parquet(panel, index=False)
    write_json(asset_root / "fixture_seed_manifest.json", {
        "panel_relative": panel.name, "panel_sha256": sha(panel),
        "panel_max_date": through_date, "panel_rows": len(seed_rows),
        "production_allowed": False,
    })
    write_json(asset_root / "panel_latest.json", {"manifest_relative": "fixture_seed_manifest.json"})


_RUN_CHILD = """
import json, runpy, sys, types
from pathlib import Path
rows = json.loads(Path(sys.argv.pop(1)).read_bytes())
by_code = {item['code']: item for item in rows}
class FixtureQuoteContext:
    def __init__(self, **_):
        pass
    def get_plate_stock(self, plate):
        assert plate in {'HK.GangGuTong', 'HK.LIST1922'}
        return 0, list(by_code.values())
    def get_market_snapshot(self, codes):
        return 0, [by_code[code] for code in codes]
    def close(self):
        pass
sys.modules['futu'] = types.SimpleNamespace(OpenQuoteContext=FixtureQuoteContext)
runpy.run_path(sys.argv.pop(1), run_name='__main__')
"""

_VERIFY_CHILD_BINDING_REJECTIONS = """
import json, runpy, sys
from pathlib import Path
panel_code = runpy.run_path(sys.argv[1])
verify = panel_code['_verify_hk_packed_panel']
receipt = json.loads(Path(sys.argv[2]).read_bytes())
authority = receipt['authority']
asset, updater, date = sys.argv[3:]
codes = receipt['packed_codes']
checks = [
    (authority, '20261120', codes, 'target date mismatch'),
    (dict(authority, panel_sha256='0'*64), date, codes, 'SHA does not match'),
    (authority, date, codes[:-1]+['HK.03033'], 'exact-date membership differs'),
]
for state, day, membership, reason in checks:
    try:
        verify(asset, updater, state, day, membership)
    except ValueError as error:
        assert reason in str(error), error
    else:
        raise AssertionError(reason)
print(json.dumps({'rejected': len(checks)}))
"""

_PUBLISH_FIXTURE_MASTER = """
import sys
from pathlib import Path
from scripts.acquire_hk_security_master import _load_exact_date_hk_panel_codes
from shared_data.hk_security_master import publish_hk_security_master
import json
root, date = Path(sys.argv[1]), sys.argv[2]
codes, code_sha = _load_exact_date_hk_panel_codes(root, date)
result = publish_hk_security_master(
    root, trade_date=date, universe_codes_sha256=code_sha,
    captured_at='2026-11-23T16:30:00+08:00',
    rows=[dict(code=code, name=f'Test {code[3:]}', outstanding_shares=100_000_000,
        circular_market_val=1_000_000_000, listing_date='2010-01-01',
        lot_size=100, stock_owner='fixture', stock_child_type='fixture', sec_status='NORMAL')
        for code in codes],
)
print(json.dumps(dict(row_count=result['row_count'], artifact_sha256=result['artifact_sha256'])))
"""

_VERIFY_AND_PROJECT = """
import json, sys
from pathlib import Path
from domains.preselection_materializer import build_shared_hk_0_2_pool
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.scheduling.executor_registry_preselection import _hk_preselection_source_dates
from infrastructure.scheduling.executor_registry import _validate_hk_receipt_artifact_binding
store_root, package, target, signal, data_root, receipt_path, tdx = sys.argv[1:]
assert _hk_preselection_source_dates(signal, target) == (signal, signal)
receipt = json.loads(Path(receipt_path).read_bytes())
assert _validate_hk_receipt_artifact_binding(receipt, ['--hk-tdx-root', tdx], signal) is None
artifact = build_shared_hk_0_2_pool(Path(store_root), trade_date=target, signal_date=signal,
    shared_package_root=Path(package))
store = PreselectionPoolStore(Path(data_root))
store.materialize(artifact)
result = store.read_pool_snapshot(target, 'hkconnect_d1_top100')
print(json.dumps(result['artifact']))
"""


@pytest.mark.skipif(not RUN_OWNER_CHAIN, reason="opt-in exact local owner paths")
def test_pinned_child_panel_master_and_d1_owner_chain():
    legacy = Path(os.environ.get("V4_B4_LEGACY_HK_APP", LOCAL_LEGACY_APP))
    with TemporaryDirectory(prefix="v4-b4-hk-owner-chain-") as temporary:
        root = Path(temporary).resolve()
        store = root / "shared"
        asset_root = store / "assets" / "hk_0_2"
        tdx = root / "hk_tdx"
        receipts = root / "receipts"
        updater = stage_updater(root / "child-owner", "child-updater") / "scripts/update_hk_0_2_panel.py"
        shared = stage_updater(root / "shared-owner", "shared-updater")
        candidate_path = root / LEGACY_PANEL_PATH.name
        candidate_path.write_bytes(render_legacy_hk_day_module((legacy / LEGACY_PANEL_PATH).read_bytes()))
        rows = market_rows(601)
        expected_codes = {row["code"] for row in rows} - {"HK.03033"}
        capture = root / "synthetic_futu_reply.json"
        write_json(capture, [SnapshotFixture._snapshot(row) for row in rows])
        create_seed(asset_root, sorted(expected_codes) + ["HK.03033"])
        preserved = seed(tdx, "03033", PREVIOUS)

        envelope = run_json([
            sys.executable, "-B", "-c", _RUN_CHILD, str(capture), str(candidate_path),
            "--date", DATE, "--lane", "HK", "--receipt-root", str(receipts),
            "--hk-tdx-root", str(tdx), "--hk-asset-root", str(asset_root),
            "--hk-updater-script", str(updater), "--hk-python-executable", str(HK_PYTHON),
        ], cwd=legacy, pythonpath=legacy)
        receipt_path = receipts / f"hk-{DATE}.json"
        receipt = json.loads(receipt_path.read_bytes())
        assert envelope["overall_status"] == "READY"
        assert receipt["authority"]["through_date"] == DATE
        assert receipt["authority"]["through_date_code_count"] == 600
        assert set(receipt["packed_codes"]) == expected_codes
        assert receipt["quarantine"][0]["raw_value"] == RAW_D23_VOLUME
        assert day_path(tdx, "03033").read_bytes() == preserved

        rejected = run_json([
            sys.executable, "-B", "-c", _VERIFY_CHILD_BINDING_REJECTIONS,
            str(candidate_path), str(receipt_path), str(asset_root), str(updater), DATE,
        ], cwd=legacy, pythonpath=legacy)
        assert rejected == {"rejected": 3}

        baseline_b = asset_root / "fixture_b.parquet"
        pd.DataFrame({"code": ["HK.00001"], "date": [PREVIOUS], "close": [10.0]}).to_parquet(baseline_b, index=False)
        write_json(asset_root / "research_history.json", {
            "source_descriptor": {"sources": {"B": {"path": str(baseline_b)}}},
        })
        install_resolution(asset_root)

        published_master = run_json([
            str(HK_PYTHON), "-B", "-c", _PUBLISH_FIXTURE_MASTER, str(store), DATE,
        ], cwd=shared)
        master = run_json([
            sys.executable, "-B", "-m", "ops.ensure_hk_security_master",
            "--store-root", str(store), "--universe-root", str(store), "--shared-package-root", str(shared),
            "--trade-date", DATE, "--futu-python", str(root / "offline_fixture_no_futu"),
            "--prepare-exact-date",
        ], cwd=ACTIVE_MAIN, pythonpath=ACTIVE_MAIN)
        assert master["status"] == "READY" and master["reused"] is True
        assert master["trade_date"] == DATE and master["row_count"] == 600
        assert master["security_master_artifact_sha256"] == published_master["artifact_sha256"]

        d1 = run_json([
            str(HK_PYTHON), "-B", "-m", "scripts.materialize_hk_0_2",
            "--store-root", str(store), "--asset-root", str(asset_root),
            "--signal-date", DATE, "--target-date", NEXT,
        ], cwd=shared)
        data_root = root / "v4-data"
        artifact = run_json([
            sys.executable, "-B", "-c", _VERIFY_AND_PROJECT,
            str(store), str(shared), NEXT, DATE, str(data_root), str(receipt_path), str(tdx),
        ], cwd=ACTIVE_MAIN, pythonpath=ACTIVE_MAIN)
        assert d1["status"] == "READY"
        assert artifact["pool_id"] == "hkconnect_d1_top100"
        assert artifact["signal_date"] == DATE and artifact["target_date"] == NEXT
        assert len(artifact["rows"]) == 100
        assert {row["symbol"] for row in artifact["rows"]} <= expected_codes
        assert {row["pool_rank"] for row in artifact["rows"]} == set(range(1, 101))
        assert all(artifact[flag] is False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
        assert not (receipts / f"a-{DATE}.json").exists()
        assert not (data_root / "preselection_pools" / NEXT / "a_d1_premarket_pool.json").exists()
        print(json.dumps({
            "packed": receipt["packed_code_count"], "quarantined": receipt["quarantined_code_count"],
            "rejected_stale_or_wrong_identities": rejected["rejected"],
            "panel_sha256": receipt["authority"]["panel_sha256"],
            "master_sha256": master["security_master_artifact_sha256"],
            "pool_id": artifact["pool_id"], "pool_rows": len(artifact["rows"]),
            "pool_source_sha256": artifact["source_artifact_sha256"],
        }, sort_keys=True))


@pytest.mark.skipif(not RUN_OWNER_CHAIN, reason="opt-in exact local owner paths")
@pytest.mark.parametrize("role", ["child-updater", "shared-updater"])
@pytest.mark.parametrize(
    ("scenario", "target", "error"),
    [
        ("partial", DATE, "20261120 491/500"),
        ("partial", NEXT, "20261120 491/500"),
        ("missing", DATE, "pending securities session missing: 20261120"),
        ("zero", DATE, "20261120 trade=0.66666667 amount=1.00000000 minimum=0.80000000"),
        ("healthy", DATE, None),
    ],
)
def test_true_updaters_gate_intermediate_sessions_before_pointer_write(role, scenario, target, error):
    with TemporaryDirectory(prefix="v4-b4-hk-pending-dates-") as temporary:
        root = Path(temporary).resolve()
        package = stage_updater(root / "updater", role)
        asset_root = root / "assets"
        tdx = root / "tdx"
        count = 600
        create_seed(asset_root, [f"HK.{index:05d}" for index in range(1, count + 1)], through_date="20261119")
        pointer = asset_root / "panel_latest.json"
        original_pointer = pointer.read_bytes()
        original_seed_sha = sha(asset_root / "fixture_seed.parquet")
        pending_counts = {"partial": 491, "missing": 0, "zero": count, "healthy": count}
        directory = day_path(tdx, "00001").parent
        directory.mkdir(parents=True)
        for index in range(1, count + 1):
            dates = [DATE] if index > pending_counts[scenario] else [PREVIOUS, DATE]
            if target == NEXT:
                dates.append(NEXT)
            day_path(tdx, f"{index:05d}").write_bytes(b"".join(
                ABI.pack(
                    int(date), 10, 10.5, 9.5, 10, 200_000,
                    0 if scenario == "zero" and date == PREVIOUS and index > 400 else 1_000, 0,
                )
                for date in dates
            ))
        if role == "child-updater":
            cli = [str(package / "scripts/update_hk_0_2_panel.py")]
            app = LOCAL_LEGACY_APP
        else:
            cli = ["-m", "scripts.update_hk_0_2_panel"]
            app = ACTIVE_MAIN
        result = run_json([
            str(HK_PYTHON), "-B", *cli,
            "--asset-root", str(asset_root), "--tdx-root", str(tdx), "--through-date", target,
        ], cwd=package, pythonpath=app, expected_exit=int(error is not None))

        assert result["through_date"] == target
        assert all(result[flag] is False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
        assert sha(asset_root / "fixture_seed.parquet") == original_seed_sha
        if error is not None:
            assert result["status"] == "FAILED" and error in result["error"]
            assert pointer.read_bytes() == original_pointer
            assert not (asset_root / "panels").exists()
        else:
            assert result["status"] == "READY" and result["through_date_code_count"] == count
            manifest = json.loads((asset_root / result["manifest_relative"]).read_bytes())
            assert manifest["new_dates"] == [PREVIOUS, DATE]
            panel = pd.read_parquet(asset_root / manifest["panel_relative"])
            assert (panel.groupby("trade_date_compact")["code_norm"].nunique().loc[[PREVIOUS, DATE]] == count).all()


@pytest.mark.skipif(not RUN_OWNER_CHAIN, reason="opt-in exact local owner paths")
def test_updater_roles_reject_swapped_or_changed_preimages():
    child_source = (HK_UPDATER_ROLE_ROOTS["child-updater"] / HK_UPDATER_PATH).read_bytes()
    shared_source = (HK_UPDATER_ROLE_ROOTS["shared-updater"] / HK_UPDATER_PATH).read_bytes()
    with pytest.raises(ValueError, match="preimage SHA mismatch"):
        render_legacy_hk_updater_module(child_source, role="shared-updater")
    with pytest.raises(ValueError, match="preimage SHA mismatch"):
        render_legacy_hk_updater_module(shared_source + b"\n", role="shared-updater")
