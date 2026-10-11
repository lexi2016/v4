"""Read-only synthetic repro of shipped pure projection functions.

Not an owner run or production acceptance.  Package bootstrap skips the absent
application __init__ dependency closure; validate_attempt is compiled unchanged
from the submitted workspace source, with its original stdlib dependencies.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import importlib
import json
from pathlib import Path
import re
import sys
import types
from typing import Any, Mapping

ROOT = (Path(sys.argv[1]) if len(sys.argv) > 1 else
        Path(__file__).resolve().parents[1] / "input/V4_三路选股闭环_问题包_20261011/active_source")
if len(sys.argv) > 2:
    sys.path.insert(0, sys.argv[2])
sys.dont_write_bytecode = True
for name, path in (("v4", ROOT / "v4"), ("v4.manager_research", ROOT / "v4/manager_research")):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module

projection = importlib.import_module("v4.manager_research.workspace_projection")
attention = importlib.import_module("v4.manager_research.research_attention")
workspace = types.ModuleType("v4.manager_research.workspace")
workspace.__dict__.update(Any=Any, Mapping=Mapping, re=re,
    FLAGS=projection.FLAGS, digest=projection.digest, date_token=projection.date_token,
    timestamp=projection.timestamp, ATTEMPT_SCHEMA="v4.manager_research.workspace_attempt.v1")
source = ROOT / "v4/manager_research/workspace.py"
tree = ast.parse(source.read_text())
function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "validate_attempt")
exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), workspace.__dict__)
sys.modules[workspace.__name__] = workspace
daily = importlib.import_module("v4.manager_research.workspace_daily_channels")

DATE, SESSION = "20261009", "20261008"
REFS = [
    {"owner": "existing-panel", "payload_path": "/fixture/panel.parquet", "payload_sha256": "a" * 64,
     "manifest_path": "/fixture/panel.json", "manifest_sha256": "b" * 64},
    {"owner": "existing-master", "payload_path": "/fixture/master.json", "payload_sha256": "c" * 64,
     "manifest_path": "/fixture/master-manifest.json", "manifest_sha256": "d" * 64},
]
row = dict(code="HK.00001", name="Synthetic fixture", target_monday=int(DATE),
    verified_session=int(SESSION), qualification_status="RESEARCH_ONLY_CANDIDATE",
    classification="STRICT_REBOUND", history_status="KNOWN", source_refs=REFS,
    strict_two_gate_oversold_5dvolume=True, oversold_flag=True, volume_flag_5d_ge_1_5=True,
    reason_for_group="Synthetic original two-gate result", close=8.0,
    oversold_cutoff_80pct_prior60_high=8.2, volume_ratio_5d=1.7)
SCREEN = dict(schema_version="v4.manager_research.rebound_v3_screen.v1",
    rule_version="20260923_REBOUND_TWO_GATE_V1", target_trade_date=DATE, verified_session=SESSION,
    status="READY", main_screen_ready=True, input_identity="e" * 64,
    strict=[row], near=[], pending=[], excluded=[], screen_unresolved=[], cards=[row], gaps=[],
    coverage=dict(input_candidate_count=1, history_complete_count=1, history_pending_count=0,
        strict_count=1, near_candidate_count=0, selected_count=1, excluded_count=0,
        screen_unresolved_count=0, row_accounted_count=1))
CARDS = [dict(symbol="HK.00001", decision={}, research_attention_score=10, research_attention_band="NORMAL")]


def compare(label, screen):
    ledger = attention.build_research_selection_ledger(screen, CARDS, DATE)
    value = dict(target_trade_date=DATE, date_bindings=dict(plan_date=DATE, selection_date=DATE,
        announcement_date=SESSION), market_screen=screen, research_attention=dict(research_selection=ledger))
    channel = daily.build_daily_channels(value)["channels"][2]
    return dict(case=label, ledger_status=ledger["status"], ledger_coverage=ledger["coverage"],
        ledger_decisions=[dict(symbol=d["symbol"], status=d["decision_status"], reason=d["decision_reason_code"])
            for d in ledger["decisions"]], daily_status=channel["status"],
        daily_selected_count=channel["candidate_count"], daily_run=channel["run_id"],
        daily_execution=channel["execution_kind"], daily_decisions=[
            dict(symbol=d["symbol"], status=d["selection_status"], data_date=d["data_date"], source_refs=d["source_refs"])
            for d in channel["rows"]])


results = [compare("baseline_with_no_owner_archive", deepcopy(SCREEN))]
wrong_target = deepcopy(SCREEN)
wrong_target["target_trade_date"] = "20261008"
results.append(compare("screen_target_mismatch", wrong_target))
missing_refs = deepcopy(SCREEN)
missing_refs["strict"][0]["source_refs"] = []
results.append(compare("missing_original_source_refs", missing_refs))
contradiction = deepcopy(SCREEN)
contradiction["strict"][0]["oversold_flag"] = False
results.append(compare("strict_row_rule_contradiction", contradiction))
duplicate = deepcopy(SCREEN)
duplicate["strict"].append(deepcopy(duplicate["strict"][0]))
duplicate["cards"] = list(duplicate["strict"])
duplicate["coverage"].update(input_candidate_count=2, history_complete_count=2, strict_count=2,
    selected_count=2, row_accounted_count=2)
results.append(compare("duplicate_symbol", duplicate))
future = deepcopy(SCREEN)
future["verified_session"] = "20261010"
future["strict"][0]["verified_session"] = 20261010
results.append(compare("future_market_session", future))

empty = deepcopy(SCREEN)
empty["strict"] = []; empty["cards"] = []
empty["excluded"] = [dict(row, classification="EXCLUDED_REBOUND_SCREEN", screen_decision="EXCLUDED",
    strict_two_gate_oversold_5dvolume=False, oversold_flag=False, volume_flag_5d_ge_1_5=False,
    exclusion_reason_code="BOTH_REBOUND_GATES_FAILED", reason_for_exclusion="Synthetic both gates failed")]
empty["coverage"].update(strict_count=0, selected_count=0, excluded_count=1)
results.append(compare("all_excluded_without_owner_archive", empty))

scope = dict(status="OWNER_VERIFIED", target_trade_date=DATE, codes=["HK.00001"],
    source=dict(sha256="a" * 64, market="HK_CONNECT", role="HK_CONNECT_FULL_MARKET_AUTHORITY", source_date=DATE),
    membership_semantics="TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2", gaps=[],
    calendar_applicability=dict(status="APPLICABLE", target_trade_date=DATE))
scope["identity"] = projection.digest([DATE, scope["codes"], scope["source"]["sha256"]])
hk_value = dict(target_trade_date=DATE, focus_symbols=["HK.00001"],
    stocks=[dict(symbol="HK.00001", connect_eligibility="VERIFIED_TARGET_UNIVERSE", why_watch=["Synthetic focus"])],
    owner_chain=dict(focus_inputs=dict(status="READY", gaps=[])),
    selection_diagnostics=dict(membership=scope, status="PARTIAL", connect_gaps=[], gaps=["UNRELATED_US_GAP"]))
channel = daily.build_daily_channels(hk_value)["channels"][1]
results.append(dict(case="hk_channel_global_unrelated_gap", status=channel["status"],
    candidate_count=channel["candidate_count"], gaps=channel["gaps"], run_id=channel["run_id"]))

print(json.dumps(dict(evidence_kind="SYNTHETIC_PURE_PROJECTION_ONLY", original_source_root=str(ROOT),
    writes_to_source=False, owner_executed=False, cases=results), ensure_ascii=False, indent=2))
