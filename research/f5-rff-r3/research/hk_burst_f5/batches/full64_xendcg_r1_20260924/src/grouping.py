"""Deterministic F5 session-list grouping for the native XENDCG route.

This module has no filesystem, registry, label-reader, fit, or prediction side
effects.  Callers pass already-bound arrays and key columns explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np


class GroupingError(ValueError):
    """A key, label, feature, or contiguous-group invariant was violated."""


@dataclass(frozen=True)
class GroupingPlan:
    permutation: np.ndarray
    inverse_permutation: np.ndarray
    group_sizes: np.ndarray
    grouped_sessions: np.ndarray
    grouped_codes: np.ndarray
    grouped_labels_int32: np.ndarray


def _canonical_keys(sessions: Any, codes: Any, rows: int) -> tuple[np.ndarray, np.ndarray]:
    session_values = np.asarray(sessions)
    code_values = np.asarray(codes)
    if session_values.ndim != 1 or code_values.ndim != 1 or len(session_values) != rows or len(code_values) != rows:
        raise GroupingError("KEY_LENGTH_OR_RANK_MISMATCH")
    if not np.issubdtype(session_values.dtype, np.integer):
        try:
            numeric = session_values.astype(np.float64)
        except (TypeError, ValueError) as exc:
            raise GroupingError("SESSION_ID_MUST_BE_INTEGER") from exc
        if not np.isfinite(numeric).all() or not np.equal(numeric, np.floor(numeric)).all():
            raise GroupingError("SESSION_ID_MUST_BE_INTEGER")
        session_values = numeric.astype(np.int64)
    else:
        session_values = session_values.astype(np.int64, copy=False)
    if (session_values <= 0).any():
        raise GroupingError("SESSION_ID_MUST_BE_POSITIVE")
    if code_values.dtype.kind not in "USO":
        raise GroupingError("CODE_MUST_BE_STRING")
    as_text = np.asarray([value if isinstance(value, str) else None for value in code_values], dtype=object)
    if any(value is None or not value or value.strip() != value for value in as_text):
        raise GroupingError("CODE_MUST_BE_CANONICAL_NONEMPTY_STRING")
    code_values = np.asarray(as_text, dtype=str)
    pairs = list(zip(session_values.tolist(), code_values.tolist()))
    if len(set(pairs)) != rows:
        raise GroupingError("DUPLICATE_SESSION_CODE_KEY")
    return session_values, code_values


def build_grouping_plan(
    features: Any,
    labels: Any,
    sessions: Any,
    codes: Any,
    *,
    expected_features: int = 64,
    expected_rows: int | None = None,
    expected_groups: int | None = None,
    require_original_code_session_order: bool = True,
) -> GroupingPlan:
    """Prove a single deterministic session/code permutation and its inverse."""
    x = np.asarray(features)
    y = np.asarray(labels)
    if x.ndim != 2 or x.shape[1] != expected_features:
        raise GroupingError("FEATURE_MATRIX_SHAPE_MISMATCH")
    rows = int(x.shape[0])
    if expected_rows is not None and rows != int(expected_rows):
        raise GroupingError("TRAIN_ROW_COUNT_MISMATCH")
    if x.dtype != np.dtype("float32"):
        raise GroupingError("FEATURE_MATRIX_DTYPE_MUST_BE_FLOAT32")
    if np.isinf(x).any():
        raise GroupingError("FEATURE_MATRIX_INFINITY_FORBIDDEN")
    if y.ndim != 1 or len(y) != rows:
        raise GroupingError("LABEL_LENGTH_OR_RANK_MISMATCH")
    if not np.isfinite(y).all() or not np.isin(y, (0, 1)).all():
        raise GroupingError("LABELS_MUST_BE_EXACT_BINARY_0_1")
    session_values, code_values = _canonical_keys(sessions, codes, rows)

    if require_original_code_session_order:
        canonical = np.lexsort((session_values, code_values))
        if not np.array_equal(canonical, np.arange(rows, dtype=np.int64)):
            raise GroupingError("ORIGINAL_ROWS_NOT_CODE_SESSION_ORDER")

    permutation = np.lexsort((code_values, session_values)).astype(np.int64, copy=False)
    if not np.array_equal(np.sort(permutation), np.arange(rows, dtype=np.int64)):
        raise GroupingError("PERMUTATION_NOT_BIJECTIVE")
    inverse = np.empty(rows, dtype=np.int64)
    inverse[permutation] = np.arange(rows, dtype=np.int64)
    if not np.array_equal(permutation[inverse], np.arange(rows, dtype=np.int64)):
        raise GroupingError("INVERSE_PERMUTATION_INVALID")

    grouped_sessions = session_values[permutation]
    grouped_codes = code_values[permutation]
    if rows:
        boundaries = np.r_[0, np.flatnonzero(grouped_sessions[1:] != grouped_sessions[:-1]) + 1, rows]
        group_sizes = np.diff(boundaries).astype(np.int32)
    else:
        group_sizes = np.zeros(0, dtype=np.int32)
    if int(group_sizes.sum(dtype=np.int64)) != rows:
        raise GroupingError("GROUP_SIZES_DO_NOT_COVER_ALL_ROWS")
    unique_grouped = np.unique(grouped_sessions)
    if len(unique_grouped) != len(group_sizes):
        raise GroupingError("SESSION_SPLIT_ACROSS_MULTIPLE_BLOCKS")
    if expected_groups is not None and len(group_sizes) != int(expected_groups):
        raise GroupingError("GROUP_COUNT_MISMATCH")

    if not np.array_equal(x[permutation][inverse], x, equal_nan=True):
        raise GroupingError("FEATURE_INVERSE_REORDER_MISMATCH")
    if not np.array_equal(y[permutation][inverse], y):
        raise GroupingError("LABEL_INVERSE_REORDER_MISMATCH")
    if not np.array_equal(session_values[permutation][inverse], session_values):
        raise GroupingError("SESSION_INVERSE_REORDER_MISMATCH")
    if not np.array_equal(code_values[permutation][inverse], code_values):
        raise GroupingError("CODE_INVERSE_REORDER_MISMATCH")

    return GroupingPlan(
        permutation=permutation,
        inverse_permutation=inverse,
        group_sizes=group_sizes,
        grouped_sessions=grouped_sessions,
        grouped_codes=grouped_codes,
        grouped_labels_int32=y[permutation].astype(np.int32, copy=True),
    )


def build_reference_datasets(
    lightgbm: Any,
    features: Any,
    labels: Any,
    grouping: GroupingPlan,
    *,
    dataset_params: Mapping[str, Any],
) -> tuple[Any, Any, dict[str, Any]]:
    """Construct original-order train-only bins before the grouped training view.

    The first Dataset deliberately uses original row order.  The grouped view
    references that exact object, so bin construction does not resample after
    the row permutation.  This helper never calls ``lightgbm.train``.
    """
    x = np.asarray(features)
    y = np.asarray(labels)
    if x.ndim != 2 or len(x) != len(y) or len(x) != len(grouping.permutation):
        raise GroupingError("DATASET_INPUT_ROW_COUNT_MISMATCH")
    reference = lightgbm.Dataset(
        x,
        label=y,
        params=dict(dataset_params),
        free_raw_data=False,
    )
    reference.construct()
    grouped = lightgbm.Dataset(
        x[grouping.permutation],
        label=grouping.grouped_labels_int32,
        group=grouping.group_sizes.tolist(),
        reference=reference,
        params=dict(dataset_params),
        free_raw_data=False,
    )
    grouped.construct()
    reference_chain = grouped.get_ref_chain()
    if reference not in reference_chain:
        raise GroupingError("GROUPED_DATASET_DID_NOT_INHERIT_REFERENCE")
    realized_groups = grouped.get_group()
    if realized_groups is None or not np.array_equal(np.asarray(realized_groups), grouping.group_sizes):
        raise GroupingError("LIGHTGBM_GROUP_VECTOR_MISMATCH")
    if not callable(getattr(reference, "feature_num_bin", None)) or not callable(getattr(grouped, "feature_num_bin", None)):
        raise GroupingError("LIGHTGBM_FEATURE_BIN_COUNT_API_MISSING")
    reference_bins = [int(reference.feature_num_bin(index)) for index in range(x.shape[1])]
    grouped_bins = [int(grouped.feature_num_bin(index)) for index in range(x.shape[1])]
    if reference_bins != grouped_bins:
        raise GroupingError("LIGHTGBM_REFERENCE_BIN_COUNTS_MISMATCH")
    evidence = {
        "reference_rows": int(x.shape[0]),
        "reference_order": "ORIGINAL_CODE_SESSION_CANONICAL_ORDER",
        "reference_source": "TRAIN_ONLY_ORIGINAL_X_TRAIN",
        "grouped_rows": int(x.shape[0]),
        "group_count": int(len(grouping.group_sizes)),
        "group_sum": int(grouping.group_sizes.sum(dtype=np.int64)),
        "grouped_dataset_references_exact_reference_object": True,
        "reference_object_identity": id(reference),
        "grouped_dataset_reference_chain_contains_reference": True,
        "dataset_construct_calls": 2,
        "reference_feature_bin_counts": reference_bins,
        "grouped_feature_bin_counts": grouped_bins,
        "feature_bin_counts_match": True,
        "fit_calls": 0,
        "prediction_calls": 0,
        "evaluation_data_used_as_reference": False,
        "dataset_params": dict(dataset_params),
    }
    return reference, grouped, evidence
