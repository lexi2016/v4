"""A-only research API, with the B-owned MWB_V1_20261013 types when present.

A does not redefine public contract classes, start processes, or write snapshots.
The mapping fallback supports isolated A synthetic testing before B is mounted;
production binding must install the exact frozen B contracts commit.
"""
from .common import plain
from .core import run_lanes as _run_lanes, merge_decisions as _merge_decisions
from .review import evaluate_review as _evaluate_review
from ..inputs.loader import load_inputs


def _b_type(name):
    from importlib import import_module
    try:
        contracts = import_module("v4.manager_workbench.contracts")
    except ModuleNotFoundError as exc:
        if exc.name not in ("v4.manager_workbench.contracts", "v4.manager_workbench"):
            raise
        return None
    return getattr(contracts, name)


def run_lanes(context, inputs, semantic_executor):
    values = _run_lanes(context, inputs, semantic_executor)
    model = _b_type("LaneResult")
    return {lane: model.model_validate(value) if model else value for lane,value in values.items()}


def merge_decisions(context, lane_results):
    values = _merge_decisions(context, lane_results)
    model = _b_type("StockDecision")
    return [model.model_validate(value) if model else value for value in values]


def evaluate_review(plan, close_inputs):
    value = _evaluate_review(plan, close_inputs)
    model = _b_type("ReviewSummary")
    return model.model_validate(value) if model else value

__all__=["load_inputs","run_lanes","merge_decisions","evaluate_review"]

