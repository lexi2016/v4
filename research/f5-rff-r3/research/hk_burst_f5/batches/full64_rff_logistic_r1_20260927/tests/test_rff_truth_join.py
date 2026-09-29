"""Issue #2: fabricated frames only; never invoke the training worker.

The integration test compiles the unchanged post-decode evaluation statements
from the worker, through the in-memory metrics dictionary. It does not compile
its input/fit/predict/decode or artifact-write statements. Frozen metric math is
real; machine-specific imports and control-file I/O are test-only substitutes.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import sys
from pathlib import Path
import types
from typing import Any, Mapping
from unittest import mock

import numpy as np
import pandas as pd
import pytest

ROUTE = Path(__file__).resolve().parents[1]
SLICE = next(p for p in ROUTE.parents if (p / "external_frozen_evaluator/metrics.py").is_file())
BATCHES = ROUTE.parent
WORKER_PATH = ROUTE / "src/rff_worker.py"
HISTORICAL_PATH = BATCHES / "full64_xendcg_r1_20260924/candidate_01/src/candidate_worker.py"
SCORE_PATH = BATCHES / "full64_xendcg_r1_20260924/src/score_aware_metrics.py"
FROZEN_PATH = SLICE / "external_frozen_evaluator/metrics.py"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def historical_functions():
    """Load only safe functions from unchanged source, not a second owner."""
    names = {"CandidateError", "_join_truth", "_deep_equal", "_top3_identity"}
    tree = ast.parse(HISTORICAL_PATH.read_text(encoding="utf-8"))
    body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    assert {n.name for n in body} == names
    ns = {"Any": Any, "Mapping": Mapping}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(HISTORICAL_PATH), "exec"), ns)
    return ns


@pytest.fixture
def route():
    worker = load_module("_rff_join_test_worker", WORKER_PATH)
    tree = ast.parse(WORKER_PATH.read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_candidate_worker")
    imported = any(isinstance(n, ast.ImportFrom) and n.module == "candidate_worker" and
                   any(a.name == "_join_truth" for a in n.names) for n in ast.walk(function))
    historical = historical_functions()
    # Resolve precisely the binding used by the worker, also on the RED baseline.
    join = historical["_join_truth"] if imported else worker._join_truth
    return worker, join, historical, function


def frames():
    scores = pd.DataFrame({
        "code": pd.Series(list("ABCD"), dtype="string"), "session_id": [1] * 4,
        "market_date": ["2000-01-01"] * 4, "scoreable": [1] * 4,
        "ranking_score": [3.0, 2.0, 1.0, -1.0], "probability": [.9, .8, .7, .2],
    })
    truth = scores[["code", "session_id", "market_date", "scoreable"]].copy()
    truth["y"] = [1.0, 0.0, 1.0, np.nan]
    truth["label_status"] = ["KNOWN", "KNOWN", "KNOWN", "UNKNOWN"]
    truth["first_exact"] = [2, -1, 2, -1]
    truth["episode_state"] = ["NONE", "NONE", "NONE", "UNKNOWN_NEWNESS"]
    return scores, truth


@pytest.mark.parametrize("positions", [[0, 1, 2, 3], [0, 1, 2], [3, 0, 1], []],
                         ids=["full", "top3_excludes_null", "subset_includes_null", "empty_subset"])
def test_left_domain_not_global_null_count(route, positions):
    _, join, _, _ = route
    scores, truth = frames()
    left = scores.iloc[positions].copy()
    before_left, before_truth = left.copy(deep=True), truth.copy(deep=True)
    joined = join(left, truth)
    pd.testing.assert_frame_equal(joined[left.columns], left, check_exact=True)
    pd.testing.assert_series_equal(joined.y, truth.y.iloc[positions], check_exact=True)
    pd.testing.assert_frame_equal(left, before_left, check_exact=True)
    pd.testing.assert_frame_equal(truth, before_truth, check_exact=True)


def test_order_index_score_bits_and_truth_order(route):
    _, join, _, _ = route
    scores, truth = frames()
    scores.loc[3, "ranking_score"] = -0.0
    left = scores.iloc[[3, 1, 0]].copy()
    left.index = pd.Index([20, 20, 7], name="original_index")
    joined = join(left, truth.iloc[[2, 0, 3, 1]])
    pd.testing.assert_frame_equal(joined[left.columns], left, check_exact=True)
    assert joined.ranking_score.to_numpy().tobytes() == left.ranking_score.to_numpy().tobytes()
    assert joined.y.isna().tolist() == [True, False, False]
    assert joined.y.iloc[1:].tolist() == [0., 1.]


@pytest.mark.parametrize("nullable_dtype", ["Float64", "Int64"])
def test_nullable_outcome_dtype_preserved(route, nullable_dtype):
    _, join, _, _ = route
    scores, truth = frames()
    truth["y"] = pd.array([1, 0, 1, pd.NA], dtype=nullable_dtype)
    result = join(scores.iloc[[3, 0]], truth)
    assert str(result.y.dtype) == nullable_dtype
    assert pd.isna(result.y.iloc[0]) and result.y.iloc[1] == 1


@pytest.mark.parametrize("missing_position", [0, 3])
def test_unmatched_key_fails_even_when_null_counts_cancel(route, missing_position):
    worker, join, _, _ = route
    scores, truth = frames()
    scores.loc[missing_position, "code"] = "MISSING"
    with pytest.raises(worker.RFFWorkerError, match="RFF_TRUTH_JOIN_UNMATCHED_KEY"):
        join(scores, truth)


@pytest.mark.parametrize("side", ["scores", "truth", "truth_outside_subset"])
def test_duplicate_keys_fail_closed(route, side):
    worker, join, _, _ = route
    scores, truth = frames()
    if side == "scores":
        scores = pd.concat([scores, scores.iloc[[0]]], ignore_index=True)
    else:
        truth = pd.concat([truth, truth.iloc[[3]]], ignore_index=True)
        if side == "truth_outside_subset":
            scores = scores.iloc[:3]
    with pytest.raises(worker.RFFWorkerError, match="RFF_TRUTH_JOIN_DUPLICATE_KEY"):
        join(scores, truth)


@pytest.mark.parametrize("side,key", [(side, key) for side in ("scores", "truth") for key in ("code", "session_id")])
def test_null_keys_are_not_legitimate_null_labels(route, side, key):
    worker, join, _, _ = route
    scores, truth = frames()
    frame = scores if side == "scores" else truth
    frame[key] = frame[key].astype(object)
    frame.loc[0, key] = None
    with pytest.raises(worker.RFFWorkerError, match="RFF_TRUTH_JOIN_NULL_KEY"):
        join(scores, truth)


@pytest.mark.parametrize("metadata", ["label_status", "episode_state"])
def test_required_outcome_metadata_guard_retained(route, metadata):
    worker, join, _, _ = route
    scores, truth = frames()
    truth.loc[0, metadata] = None
    with pytest.raises(worker.RFFWorkerError, match="EVALUATION_OUTCOME_METADATA_MISSING"):
        join(scores.iloc[:3], truth)


@pytest.mark.parametrize("side", ["scores", "truth", "outcome_collision"])
def test_ambiguous_columns_rejected(route, side):
    worker, join, _, _ = route
    scores, truth = frames()
    if side == "scores":
        scores = pd.concat([scores, scores[["code"]]], axis=1)
    elif side == "truth":
        truth = pd.concat([truth, truth[["y"]]], axis=1)
    else:
        scores["y"] = 0
    with pytest.raises(worker.RFFWorkerError, match="RFF_TRUTH_JOIN_AMBIGUOUS_COLUMNS"):
        join(scores, truth)


@pytest.mark.parametrize("side,column", [("scores", "code"), ("truth", "first_exact")])
def test_schema_errors_fail_closed(route, side, column):
    worker, join, _, _ = route
    scores, truth = frames()
    if side == "scores":
        scores = scores.drop(columns=column)
    else:
        truth = truth.drop(columns=column)
    with pytest.raises(worker.RFFWorkerError, match="RFF_TRUTH_JOIN_SCHEMA_MISMATCH"):
        join(scores, truth)


def test_composite_key_not_code_alone(route):
    _, join, _, _ = route
    scores, truth = frames()
    second_scores, second_truth = scores.copy(), truth.copy()
    second_scores["session_id"] = second_truth["session_id"] = 2
    second_truth["y"] = [0., 1., 0., np.nan]
    left = pd.concat([second_scores.iloc[:3], scores.iloc[:3]], ignore_index=True)
    result = join(left, pd.concat([truth, second_truth], ignore_index=True))
    assert result.y.tolist() == [0., 1., 0., 1., 0., 1.]
    pd.testing.assert_frame_equal(result[left.columns], left, check_exact=True)


@pytest.fixture(scope="module")
def metric_modules():
    assert hashlib.sha256(SCORE_PATH.read_bytes()).hexdigest() == "fc93d6225c75b633981508a18c428e7649122571c7d897264d0b7da1e591eb8c"
    assert hashlib.sha256(FROZEN_PATH.read_bytes()).hexdigest() == "c8ffabf345069d64a82ac686e6747afda8c22433f1309eecdc999a7ad1eac763"
    settings = types.ModuleType("_rff_synthetic_frozen.settings")
    # Test fixture only. No signed settings/contract is loaded or modified.
    settings.CONTRACT = {"calibration_bins": [0., .5, 1.]}
    package = types.ModuleType("_rff_synthetic_frozen")
    package.__path__ = []
    # Keep lazy-imported native dependencies cached; undo only our two entries.
    # One evaluator/wrapper pair is shared by both parameter cases in this module.
    with pytest.MonkeyPatch.context() as modules:
        modules.setitem(sys.modules, "_rff_synthetic_frozen", package)
        modules.setitem(sys.modules, "_rff_synthetic_frozen.settings", settings)
        frozen = load_module("_rff_synthetic_frozen.metrics", FROZEN_PATH)
        score = load_module("_rff_synthetic_score", SCORE_PATH)
        with mock.patch.object(score, "frozen_metrics", return_value=frozen):
            yield score, frozen


def evaluation_tail(function):
    body = next(n for n in function.body if isinstance(n, ast.Try)).body
    def assigns(node, name):
        return isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
    begin = next(i for i, n in enumerate(body) if assigns(n, "candidate_frame"))
    end = next(i for i, n in enumerate(body) if assigns(n, "metrics"))
    statements = body[begin:end + 1]
    assert assigns(statements[0], "candidate_frame") and assigns(statements[1], "selected")
    forbidden = {"core", "_read_csv_bytes", "_load_bound_inputs", "_write_exclusive",
                 "fit_logistic", "predict_full_eval", "run_candidate_worker"}
    assert not any(isinstance(n, ast.Name) and n.id in forbidden for s in statements for n in ast.walk(s))
    return compile(ast.Module(body=statements, type_ignores=[]), str(WORKER_PATH), "exec")


@pytest.mark.parametrize("null_selected", [False, True], ids=["top3_no_null", "top3_with_null"])
def test_worker_evaluation_handoff_synthetic(route, metric_modules, null_selected):
    worker, join, historical, function = route
    score, frozen = metric_modules
    scores, truth = frames()
    if null_selected:
        scores.loc[3, "ranking_score"] = 4.
    selected = score.select_top3(scores, score_kind=score.RAW_RANKING_SCORE, score_column="ranking_score")
    before_scores, before_truth = scores.copy(deep=True), truth.copy(deep=True)
    control = scores.copy()
    for c in ["y", "label_status", "first_exact", "episode_state"]:
        control[c] = truth[c].array
    keys = ("FROZEN_UNWEIGHTED_PLUS_PATH", "FROZEN_BASE34")
    controls = {k: {"scores": control.copy(), "top3_path": "synthetic://" + k} for k in keys}
    synthetic_sha = hashlib.sha256(b"synthetic-only-no-real-artifact").hexdigest()
    ns = dict(historical, _join_truth=join, RFFWorkerError=worker.RFFWorkerError,
              _call_budget=worker._call_budget, np=np, pd=pd, score_aware_metrics=score,
              eval_scores=scores, selected_pretruth=selected, truth=truth,
              calendar=pd.DataFrame({"session_id": [1], "market_date": ["2000-01-01"]}),
              binding={"baseline_artifacts": {k: {"scores_sha256": synthetic_sha} for k in keys}},
              evaluation={"selection_slots": 3, "known_positive_denominator": 2},
              spec={"route_id": "SYNTHETIC_ONLY", "decision_gates": {"original_promotion_gates_unchanged": {}}},
              execution_id="SYNTHETIC_ONLY", fit_calls=0, fit_entered=False, fit_returned=0,
              predict_calls=0, truth_decodes=0, truth_decoded=False,
              seal_sha=synthetic_sha, fit_receipt_sha=synthetic_sha, model_sha=synthetic_sha,
              scores_sha=synthetic_sha, raw_sha=synthetic_sha, top3_sha=synthetic_sha,
              optimizer_path="synthetic://optimizer")
    def synthetic_read(path, **kwargs):
        assert path in {v["top3_path"] for v in controls.values()}
        return frozen.select_top3(control).copy()
    def synthetic_hash(path):
        assert path == "synthetic://optimizer"
        return synthetic_sha
    ns["_sha256_file"] = synthetic_hash
    ns["_load_control_artifacts"] = mock.Mock(return_value=controls)
    with mock.patch.object(pd, "read_csv", side_effect=synthetic_read):
        exec(evaluation_tail(function), ns)
    result = ns["metrics"]  # In-memory synthetic result; never written as a receipt.
    assert result["grid_rows"] == 4 and result["selection_slots"] == 3
    arm = result["arms"]["CANDIDATE_RFF_LOGISTIC"]
    assert arm["unknown_selected"] == int(null_selected)
    assert arm["hits_known"] == (1 if null_selected else 2)
    assert arm["precision_lower"] == pytest.approx((1 if null_selected else 2) / 3)
    assert arm["precision_upper"] == pytest.approx(2 / 3)
    assert arm["probability"]["known"] == 3 and arm["probability"]["unknown"] == 1
    for key in keys:
        assert result["binary_control_evaluator_outputs_deep_equal_to_original"][key] is True
        assert result["paired_precision"][key]["denominator"] == 3
    assert result["fit_calls"] == result["predict_calls"] == result["evaluation_truth_decodes"] == 0
    assert result["safety"] == {"research_only": True, "production_allowed": False,
                                "buy_gate_updated": False, "orders_sent": False}
    pd.testing.assert_frame_equal(scores, before_scores, check_exact=True)
    pd.testing.assert_frame_equal(truth, before_truth, check_exact=True)


@pytest.mark.parametrize("bad_frame", ["full_grid", "top3"])
def test_worker_tail_bad_key_stops_before_evaluator(route, bad_frame):
    worker, join, _, function = route
    scores, truth = frames()
    selected = scores.iloc[:3].copy()
    target = scores if bad_frame == "full_grid" else selected
    target.loc[0, "code"] = "MISSING"
    controls = mock.Mock(side_effect=AssertionError("must not reach evaluator"))
    ns = {"_join_truth": join, "eval_scores": scores, "selected_pretruth": selected,
          "truth": truth, "_load_control_artifacts": controls}
    with pytest.raises(worker.RFFWorkerError, match="RFF_TRUTH_JOIN_UNMATCHED_KEY"):
        exec(evaluation_tail(function), ns)
    controls.assert_not_called()


def test_worker_execution_body_unchanged_except_import():
    # Pins resource trace admission, L04 handoff, fit/predict/decode, and metric
    # definitions to the upstream body. Only the obsolete join import may differ.
    source = WORKER_PATH.read_text(encoding="utf-8")
    marker = 'def run_candidate_worker(payload: Mapping[str, Any]) -> dict[str, Any]:'
    body = source[source.index(marker):].replace("        _join_truth,\n", "")
    assert hashlib.sha256(body.encode("utf-8")).hexdigest() == "db2ffa81da628554c35d2bd686071a613ac68aa1a57a6192b17f9ed0f61fb90d"
