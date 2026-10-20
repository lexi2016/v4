"""Exercise the original scheduler's lane entry using synthetic local inputs only."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads((ROOT / "baseline_manifest.json").read_text())
TARGET = "20261019"

FORMULA_SCRIPT = '''
import json
import pyarrow as pa
import pyarrow.parquet as pq
def main(_):
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    for pointer in (SELECTOR_POINTER, BACKTEST_POINTER):
        path = __import__('pathlib').Path(pointer.read_text().strip())
        pq.write_table(pa.table({'trade_date': [20261016, 20261019, 20261019]}), path)
    (RUN_DIR / 'task_summary.json').write_text(json.dumps({
        'final_status': 'PASS_SYNTHETIC', 'selector_increment_rows': 2}))
'''

HARNESS = '''
import sys
from ops import macos_research_panel_daily as daily
sync = {
    'status': 'READY', 'authority_status': 'REBUILD_REQUIRED',
    'accepted_count': 3, 'accepted_target_date_file_count': 3,
    'target_date_file_count': 3, 'target_count': 4, 'quarantine_count': 1,
    'coverage_rate': 0.75, 'formula_input_mode': 'ACCEPTED_ONLY',
    'reconciliation': {'accepted_count': 3, 'quarantine_count': 1,
                       'target_count': 4, 'pending_count': 0},
}
daily.run_windows_a_sync_authority = lambda *a, **kw: sync
sys.argv = ['ops.macos_research_panel_daily', *sys.argv[1:]]
raise SystemExit(daily.main())
'''


def projection(tmp_path):
    runtime = Path(BASELINE["runtime_root"])
    app = tmp_path / "app"
    (app / "ops").mkdir(parents=True)
    (app / "ops/__init__.py").write_text("")
    baseline_mode = os.environ.get("RECEIPT_COUNT_BASELINE") == "1"
    for relative, expected in BASELINE["files"].items():
        original = runtime / relative
        permitted = {expected}
        if relative in BASELINE["allowed_delta"] and not baseline_mode:
            permitted.add(hashlib.sha256((ROOT / "source" / relative).read_bytes()).hexdigest())
        assert hashlib.sha256(original.read_bytes()).hexdigest() in permitted, relative
        source = original
        if relative in BASELINE["allowed_delta"] and not baseline_mode:
            source = ROOT / "source" / relative
        shutil.copyfile(source, app / relative)
    return app


def inputs(tmp_path, fresh):
    data = tmp_path / "synthetic"
    data.mkdir()
    selector, backtest = data / "selector.parquet", data / "backtest.parquet"
    dates = [20261016] if fresh else [20261016, 20261019, 20261019]
    for path in (selector, backtest):
        pq.write_table(pa.table({"trade_date": dates}), path)
    for role, path in (("selector", selector), ("backtest", backtest)):
        (data / (role + ".txt")).write_text(str(path) + "\n")
    formula = data / "synthetic_formula.py"
    formula.write_text(FORMULA_SCRIPT)
    day = data / "tdx/vipdoc/sh/lday/sh600001.day"
    day.parent.mkdir(parents=True)
    day.write_bytes(b"synthetic-input-never-read-by-stub-sync")
    paths = {
        "receipt-root": data / "receipts", "a-tdx-root": data / "tdx",
        "hk-tdx-root": data / "unused_hk", "a-sync-script": data / "unused_sync.py",
        "a-formula-script": formula, "a-seed-panel": selector,
        "a-data-root": data, "a-selector-pointer": data / "selector.txt",
        "a-backtest-pointer": data / "backtest.txt", "a-selector-seed": selector,
        "a-backtest-seed": backtest, "a-contract-csv": data / "unused_contract.csv",
        "a-canonical-formula": data / "unused_canonical.py",
        "a-return-root": data / "formula_runs", "hk-updater-script": data / "unused_hk.py",
        "hk-asset-root": data / "unused_hk_assets",
    }
    argv = ["--date", TARGET, "--lane", "A"]
    for name, path in paths.items():
        argv.extend(["--" + name, str(path)])
    return data, argv


def automatic_call(app, data, argv):
    env = dict(os.environ, PYTHONPATH=str(app), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, "-c", HARNESS, *argv], cwd=app,
                            env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    envelope = json.loads(result.stdout)
    receipt = json.loads((data / "receipts" / ("a-" + TARGET + ".json")).read_text())
    assert envelope["lanes"]["A"]["row_count"] == receipt["row_count"]
    return receipt


@pytest.mark.parametrize("fresh", [True, False], ids=["fresh", "already_current"])
def test_automatic_entry_preserves_distinct_counts_on_first_run_and_retry(tmp_path, fresh):
    app = projection(tmp_path)
    data, argv = inputs(tmp_path, fresh)
    for attempt in range(2):
        receipt = automatic_call(app, data, argv)
        assert receipt["accepted_count"] == 3
        assert receipt["accepted_target_date_file_count"] == 3
        assert receipt["row_count"] == 2
        assert receipt["coverage_rate"] == 0.75
        assert receipt["reconciliation"]["accepted_count"] == 3
        assert receipt["formula"].get("already_current", False) == (not fresh or attempt > 0)
        assert receipt["selector_sha256"] == hashlib.sha256((data / "selector.parquet").read_bytes()).hexdigest()
        assert all(receipt[k] is False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))


@pytest.mark.parametrize("failure", ["unbound", "wrong_sha", "invalid_parquet", "fresh_missing_metric"])
def test_unavailable_selector_count_cannot_fall_back_to_accepted_input_count(tmp_path, failure):
    app = projection(tmp_path)
    selector = tmp_path / "selector.parquet"
    if failure == "invalid_parquet":
        selector.write_bytes(b"invalid parquet")
    else:
        pq.write_table(pa.table({"trade_date": [20261019, 20261019]}), selector)
    formula = {"already_current": failure != "fresh_missing_metric"}
    if failure != "unbound":
        formula.update(selector=str(selector), selector_sha256=(
            "0" * 64 if failure == "wrong_sha" else hashlib.sha256(selector.read_bytes()).hexdigest()))
    script = '''
import json, sys
from ops.macos_research_panel_daily_receipts import build_a_lane_outcome
from ops.macos_research_panel_daily_common import SnapshotGateError
try:
    build_a_lane_outcome({'accepted_target_date_file_count': 3, 'coverage_rate': .75},
                         json.loads(sys.argv[1]), '20261019', None)
except SnapshotGateError:
    pass
else:
    raise AssertionError('unavailable selector count incorrectly fell back to accepted files')
'''
    result = subprocess.run([sys.executable, "-c", script, json.dumps(formula)], cwd=app,
                            env=dict(os.environ, PYTHONPATH=str(app), PYTHONDONTWRITEBYTECODE="1"),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
