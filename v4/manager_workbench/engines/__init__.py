"""A-only research API; B owns execution, public types and persistence.

All return values conform to MWB_V1_20261013 JSON field names. Before B's
fixed public-contract commit is available, these are plain mapping values,
not a substitute public contract implementation.
"""
from .core import run_lanes, merge_decisions
from .review import evaluate_review
__all__=["run_lanes","merge_decisions","evaluate_review"]
