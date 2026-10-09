"""Classify the reviewer edge failure without changing the production identity."""
from copy import deepcopy
from datetime import timedelta
import importlib
import json
from pathlib import Path

import pytest

from test_independent_edges import app_owner, material_owner, DATE, _snapshot, clocks


@pytest.mark.parametrize("kind", ["SCHEDULED_MORNING", "SCHEDULED_PREOPEN"])
def test_same_scheduled_cutoff_reuses_run_when_only_native_witness_advances(material_owner, monkeypatch, kind):
    service, _client, roots, witness, _owner, _built = material_owner
    workspace = importlib.import_module(service.__class__.__module__.rsplit(".", 1)[0] + ".workspace")
    now, deadline = clocks(kind)
    witness[0] = now
    monkeypatch.setattr(workspace, "_now", lambda: witness[0].isoformat())
    first = service.refresh_workspace_plan(DATE, execution_kind=kind, now=now, deadline=deadline)
    before = _snapshot(roots["manager"])
    witness[0] += timedelta(seconds=30)
    repeated = service.refresh_workspace_plan(DATE, execution_kind=kind, now=now, deadline=deadline)
    assert repeated["plan_product"]["status"] == "ALREADY_MATERIALIZED"
    assert repeated["plan_product"]["run_id"] == first["plan_product"]["run_id"]
    assert repeated["input_identity"] == first["input_identity"]
    assert _snapshot(roots["manager"]) == before


@pytest.mark.parametrize("kind", ["SCHEDULED_MORNING", "SCHEDULED_PREOPEN"])
def test_advancing_cutoff_identity_difference_is_existing_screen_context(material_owner, monkeypatch, kind):
    service, _client, roots, witness, _owner, _built = material_owner
    workspace = importlib.import_module(service.__class__.__module__.rsplit(".", 1)[0] + ".workspace")
    now, deadline = clocks(kind)
    witness[0] = now
    monkeypatch.setattr(workspace, "_now", lambda: witness[0].isoformat())
    inputs = []
    real_project = workspace.project
    def trace_project(service, name, payload, function):
        if name == "workspace_projection":
            inputs.append(deepcopy(payload[1]))
        return real_project(service, name, payload, function)
    monkeypatch.setattr(workspace, "project", trace_project)
    first = service.refresh_workspace_plan(DATE, execution_kind=kind, now=now, deadline=deadline)
    before_sources = {key: _snapshot(roots[key]) for key in ("shared", "research")}
    witness[0] += timedelta(seconds=30)
    repeated = service.refresh_workspace_plan(DATE, execution_kind=kind, now=witness[0], deadline=deadline)
    assert first["input_identity"] != repeated["input_identity"]
    assert first["plan_product"]["run_id"] != repeated["plan_product"]["run_id"]
    assert {key: _snapshot(roots[key]) for key in before_sources} == before_sources
    a, b = inputs
    def paths(a, b, path=""):
        if isinstance(a, dict) and isinstance(b, dict):
            return [item for k in sorted(set(a) | set(b)) for item in paths(a.get(k), b.get(k), path + "." + k)]
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            return [item for i in range(len(a)) for item in paths(a[i], b[i], path + "[" + str(i) + "]")]
        return [] if a == b else [path]
    differences = paths(a, b)
    assert differences == [".market_screen.data_context.research_cutoff", ".plan_context.research_cutoff"]
    b["plan_context"]["research_cutoff"] = a["plan_context"]["research_cutoff"]
    b["market_screen"]["data_context"]["research_cutoff"] = a["market_screen"]["data_context"]["research_cutoff"]
    assert a == b
    payload = {"kind": kind, "changed_projection_inputs": differences,
               "same_source_bytes": True, "same_witness_only_reuse": "separately tested",
               "classification": "EXISTING_CUTOFF_SENSITIVE_SCREEN_IDENTITY_OUTSIDE_TWO_FILE_PATCH"}
    (Path(__file__).parent / ("clock_classification_" + kind + ".json")).write_text(json.dumps(payload, indent=2) + "\n")
