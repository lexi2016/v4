"""Synthetic injected-owner input repro; unchanged submitted screen algorithm.

No collection, owner execution, real calendar claim, or production data writes.
Demonstrates complete numeric data suppressing a provenance repair source.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timedelta
import importlib
import inspect
import json
from pathlib import Path
import sys
import types
import pandas as pd

ROOT = (Path(sys.argv[1]) if len(sys.argv) > 1 else
        Path(__file__).resolve().parents[1] / "input/V4_三路选股闭环_问题包_20261011/active_source")
sys.dont_write_bytecode = True
for name, path in (("v4", ROOT / "v4"), ("v4.manager_research", ROOT / "v4/manager_research")):
    module = types.ModuleType(name); module.__path__ = [str(path)]; sys.modules[name] = module
for name in ("v3_shared_data", "v3_shared_data.shared_data", "upstreams", "upstreams.v3_shared_data",
             "upstreams.v3_shared_data.shared_data"):
    module = types.ModuleType(name); module.__path__ = []; sys.modules[name] = module
for name, exception in (("v3_shared_data.shared_data.store", "StoreError"),
                       ("upstreams.v3_shared_data.shared_data.hk_security_master", "HKSecurityMasterReadError")):
    module = types.ModuleType(name)
    setattr(module, exception, type(exception, (ValueError,), {})); sys.modules[name] = module
wp = importlib.import_module("v4.manager_research.workspace_plan")
DAY = "20261008"; TARGET = "20261009"; CODE = "HK.00001"
base = datetime.strptime(DAY, "%Y%m%d")
prior60 = [(base - timedelta(days=i)).strftime("%Y%m%d") for i in range(1, 61)]
prior5 = prior60[:5]
context = dict(plan_trade_date=TARGET, market_session=DAY, research_cutoff="2026-10-11T12:00:00+08:00",
    screen_phase="PREOPEN_COMPLETED_SESSION", screen_session_policy="SYNTHETIC_CALENDAR_FIXTURE")
wp.screen_context = lambda value: value
wp.rebound_history_sessions = lambda day: dict(prior60=prior60, previous5=prior5, calendar_sha256="c" * 64)
panel = dict(owner="V4_SHARED_HK_0_2_PANEL_AUTHORITY", panel_path="/synthetic/panel.parquet",
    panel_sha256="a" * 64, panel_manifest_path="/synthetic/panel-manifest.json",
    panel_manifest_sha256="b" * 64, panel_available_at="2026-10-08T18:00:00+08:00",
    source_contract="SYNTHETIC_EXACT_PANEL")
master = dict(owner="V4_SHARED_HK_SECURITY_MASTER_AUTHORITY", names={CODE:{"name":"Synthetic"}},
    captured_at="2026-10-08T18:00:00+08:00", artifact_path="/synthetic/master.json",
    artifact_sha256="d" * 64, manifest_path="/synthetic/master-manifest.json", manifest_sha256="e" * 64)
wp._read_hk02_panel_witness = lambda *a, **k: (deepcopy(panel), [])
wp._screen_security_master_witness = lambda *a, **k: (deepcopy(master), {})
# Exact fields emitted by the original native-v1 evidence path: inherited scale
# is not attested. The experiment concerns the source-selection branch, not the
# original authority reader's cryptographic verifier.
wp._screen_panel_volume_evidence = lambda panel, ctx, sessions: dict(status="NOT_PROVEN",
    unit_status="NOT_PROVEN", unit=None, scale_applied=None, source=panel["owner"],
    gaps=["SCREEN_VOLUME_UNIT_OR_SCALE_NOT_PROVEN"])

supplement_calls = []
def supplement_reader(*args, **kwargs):
    supplement_calls.append(True)
    return dict(target_date=DAY, status="READY", raw_capture_sha256="f" * 64,
        manifest_sha256="1" * 64, pointer=dict(raw_capture_relative="synthetic-raw.json",
            manifest_relative="synthetic-manifest.json"), manifest=dict(run_id="fixture", method="get_instrument_bars"),
        records={CODE:dict(status="READY", request_sha256="2" * 64, response_sha256="3" * 64,
            bars=[dict(trade_date=date, open=8.0, high=10.0, low=7.0, close=8.0,
                trade=200 if date == DAY else 100) for date in [*prior5, DAY]])})
wp._read_hk02_daily_supplement_witness = supplement_reader

rows = [dict(trade_date_compact=date, code_norm=CODE, name="Synthetic", open=8.0,
    high=10.0, low=7.0, close=8.0, amount=1000000.0, trade=100.0, pre_close=8.0) for date in prior60]
rows.append(dict(trade_date_compact=DAY, code_norm=CODE, name="Synthetic", open=8.0,
    high=10.0, low=7.0, close=8.0, amount=1000000.0, trade=200.0, pre_close=8.0))

results = []
for label, volume in (("canonical_target_volume_missing", None), ("canonical_target_volume_recovered", 200.0),
                      ("present_prior_session_missing_high_field", None)):
    fixture = deepcopy(rows); fixture[-1]["trade"] = volume
    if label == "present_prior_session_missing_high_field":
        fixture[10]["high"] = None
    pd.read_parquet = lambda *a, **k: pd.DataFrame(fixture)
    supplement_calls.clear()
    diagnostics = {}
    kwargs = {"diagnostics": diagnostics} if "diagnostics" in inspect.signature(wp.read_rebound_screen).parameters else {}
    output = wp.read_rebound_screen(Path("/synthetic/authority"), context, **kwargs)
    all_rows = [r for group in ("strict", "near", "pending", "excluded", "screen_unresolved") for r in output.get(group, [])]
    result_row = all_rows[0] if all_rows else {}
    results.append(dict(case=label, supplement_read_count=len(supplement_calls), status=output["status"],
        strict_count=len(output.get("strict", [])), pending_count=len(output.get("pending", [])),
        volume_source=result_row.get("volume_source"), history_status=result_row.get("history_status"),
        history_unknown_reasons=result_row.get("history_unknown_reasons"), gaps=output.get("gaps"),
        diagnostic_rows=diagnostics.get("rows")))
print(json.dumps(dict(evidence_kind="SYNTHETIC_INJECTED_OWNER_WITNESS_ONLY", owner_executed=False,
    original_screen_source=str(ROOT / "v4/manager_research/workspace_plan.py"), cases=results), indent=2))
