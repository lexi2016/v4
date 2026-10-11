"""Synthetic readback-boundary probe; no source edits or actual owner execution.

The original source functions are compiled unchanged. The storage boundary is
an in-memory fixture, so these results cannot attest an archive or a live run.
"""
from __future__ import annotations

import ast
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import io
import json
from pathlib import Path
import runpy
import sys

fixture_path = Path(__file__).with_name("repro_daily_channels.py")
with redirect_stdout(io.StringIO()):
    fixture = runpy.run_path(str(fixture_path))
wp = fixture["workspace"]
daily = fixture["daily"]
identity = importlib.import_module("v4.manager_research.workspace_identity")
source = fixture["source"]
names = {"_now", "seal_attempt", "_read_plan", "_overlay_us_mapping_attempt",
         "verified_plan_attempt", "_plan_run_readback", "_readback_plan"}
tree = ast.parse(source.read_text())
wp.__dict__.update(datetime=datetime, timezone=timezone, deepcopy=deepcopy,
    HK=fixture["projection"].HK, PLAN_SCHEMA="v4.manager_research.workspace_plan_product.v1",
    _ERROR_TYPES=(ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError, TimeoutError),
    input_identity_diagnostics=identity.input_identity_diagnostics)
exec(compile(ast.Module(body=[node for node in tree.body
    if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[]), str(source), "exec"), wp.__dict__)

DATE = fixture["DATE"]
RUN = "a" * 32
LATER = "b" * 32
OWNER = "ManagerResearchJobService.refresh_workspace_plan"
screen = deepcopy(fixture["empty"])
ledger = fixture["attention"].build_research_selection_ledger(screen, [], DATE)
value = dict(target_trade_date=DATE, date_bindings=dict(plan_date=DATE,
    selection_date=DATE, announcement_date=fixture["SESSION"]),
    market_screen=screen, research_attention=dict(research_selection=ledger),
    input_identity="d" * 64, input_identity_schema=identity.INPUT_IDENTITY_SCHEMA,
    input_identity_components={"synthetic_screen": identity.identity_component(screen)},
    semantic_version="synthetic-readback-fixture",
    plan_context=dict(research_cutoff="2026-10-09T10:00:00+08:00"))
value["daily_channels"] = daily.build_daily_channels(value)
product = dict(schema_version=wp.PLAN_SCHEMA, target_trade_date=DATE,
    run_id=RUN, generated_at="2026-10-09T10:00:01+08:00", owner=OWNER,
    execution_kind="MANUAL_REFRESH", input_identity=value["input_identity"],
    workspace=deepcopy(value), **wp.FLAGS)
product["sha256"] = wp.digest(product)
attempt = wp.seal_attempt(dict(schema_version=wp.ATTEMPT_SCHEMA,
    target_trade_date=DATE, run_id=RUN, owner=OWNER, state="SUCCEEDED_EMPTY",
    execution_kind="MANUAL_REFRESH", started_at="2026-10-09T10:00:00+08:00",
    finished_at="2026-10-09T10:00:02+08:00", failure_reasons=[],
    input_identity=value["input_identity"], **wp.FLAGS))
later = wp.seal_attempt(dict(schema_version=wp.ATTEMPT_SCHEMA,
    target_trade_date=DATE, run_id=LATER, owner=OWNER, state="FAILED",
    execution_kind="MANUAL_REFRESH", started_at="2026-10-09T10:05:00+08:00",
    finished_at="2026-10-09T10:05:02+08:00", failure_reasons=["SYNTHETIC_LATER_FAILURE"],
    **wp.FLAGS))


class MemoryReadFixture:
    root = Path("/synthetic/not-an-archive")

    def __init__(self):
        self.records = {
            f"workspace_plans/{DATE}/latest.json": deepcopy(product),
            f"workspace_plan_runs/{DATE}/{RUN}.json": deepcopy(attempt),
            f"workspace_plan_runs/{DATE}/latest.json": deepcopy(attempt),
        }

    def _read(self, path):
        return deepcopy(self.records.get(str(path.relative_to(self.root))))


store = MemoryReadFixture()
results = []
for label, latest_attempt in (("same_saved_and_latest_attempt", attempt),
                              ("later_failed_attempt_same_saved_product", later)):
    store.records[f"workspace_plan_runs/{DATE}/latest.json"] = deepcopy(latest_attempt)
    got = wp._readback_plan(store, DATE, deepcopy(value),
        read_at=datetime.fromisoformat("2026-10-09T10:10:00+08:00"))
    channel = next(row for row in daily.build_daily_channels(got)["channels"]
                   if row["channel"] == "OVERSOLD")
    results.append(dict(case=label, plan_status=got["plan_product"]["status"],
        consumed=got["plan_product"]["consumed"],
        exact_run_readback=got["plan_product"]["run_readback"],
        displayed_latest_attempt_run=got["workspace_plan_attempt"]["run_id"],
        channel_status=channel["status"], channel_run_id=channel["run_id"],
        channel_product_sha256=channel["product_sha256"],
        channel_execution_kind=channel["execution_kind"],
        channel_count=channel["candidate_count"], channel_gaps=channel["gaps"]))
assert store.records[f"workspace_plans/{DATE}/latest.json"] == product
print(json.dumps(dict(evidence_kind="SYNTHETIC_IN_MEMORY_READBACK_BOUNDARY_ONLY",
    owner_executed=False, source_root=str(fixture["ROOT"]),
    unchanged_product_sha256=product["sha256"], cases=results), indent=2))
