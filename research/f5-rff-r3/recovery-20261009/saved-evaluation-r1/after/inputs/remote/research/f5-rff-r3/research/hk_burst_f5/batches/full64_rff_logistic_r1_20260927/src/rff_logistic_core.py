"""Frozen FULL64 train-only preprocessing and RFF logistic objective.

This module has no data-loading, owner, registry, or evaluation side effects.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit


RFF_DIMENSION = 256
RFF_GAMMA = 1.0 / 64.0
RFF_SEED = 42
TRANSFORM_CHUNK_ROWS = 4096
LOGISTIC_C = 1.0
L_BFGS_B_OPTIONS = {
    "ftol": 2.220446049250313e-9,
    "gtol": 1e-5,
    "maxiter": 200,
    "maxfun": 5000,
    "maxls": 20,
    "maxcor": 10,
}


class RFFContractError(ValueError):
    pass


class OptimizerNotConverged(RuntimeError):
    def __init__(self, optimizer_result: Mapping[str, Any]):
        super().__init__("STOP_OPTIMIZER_NOT_CONVERGED")
        self.optimizer_result = optimizer_result


def fit_preprocessor(x_train: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return per-column train means/stds; all-NaN and constant columns scale to 1."""
    x = np.asarray(x_train)
    if x.ndim != 2 or x.shape[0] == 0 or x.shape[1] == 0:
        raise RFFContractError("TRAIN_MATRIX_SHAPE_INVALID")
    values = np.asarray(x, dtype=np.float64)
    if np.isinf(values).any():
        raise RFFContractError("FEATURE_INFINITY_FORBIDDEN")
    means = np.zeros(values.shape[1], dtype=np.float64)
    scales = np.ones(values.shape[1], dtype=np.float64)
    for column_index in range(values.shape[1]):
        column = values[:, column_index]
        observed = column[~np.isnan(column)]
        if observed.size == 0:
            continue
        mean = float(observed.mean(dtype=np.float64))
        variance = float(np.mean(np.square(observed - mean), dtype=np.float64))
        scale = float(np.sqrt(variance))
        means[column_index] = mean
        scales[column_index] = scale if np.isfinite(scale) and scale > 0.0 else 1.0
    if not np.isfinite(means).all() or not np.isfinite(scales).all():
        raise RFFContractError("TRAIN_PREPROCESSOR_NONFINITE")
    return means, scales


def make_rff_parameters(
    n_features: int = 64,
    *,
    dimension: int = RFF_DIMENSION,
    gamma: float = RFF_GAMMA,
    seed: int = RFF_SEED,
) -> tuple[np.ndarray, np.ndarray]:
    if n_features <= 0 or dimension <= 0 or not np.isfinite(gamma) or gamma <= 0:
        raise RFFContractError("RFF_PARAMETER_INVALID")
    rng = np.random.RandomState(seed)
    projection = rng.normal(
        loc=0.0,
        scale=np.sqrt(2.0 * gamma),
        size=(n_features, dimension),
    ).astype(np.float64, copy=False)
    phase = rng.uniform(0.0, 2.0 * np.pi, size=dimension).astype(np.float64, copy=False)
    return projection, phase


def transform_rff(
    x: np.ndarray,
    means: np.ndarray,
    scales: np.ndarray,
    projection: np.ndarray,
    phase: np.ndarray,
    *,
    chunk_rows: int = TRANSFORM_CHUNK_ROWS,
) -> np.ndarray:
    """Project inputs in bounded chunks into one preallocated float64 RFF matrix."""
    matrix = np.asarray(x)
    means = np.asarray(means, dtype=np.float64)
    scales = np.asarray(scales, dtype=np.float64)
    projection = np.asarray(projection, dtype=np.float64)
    phase = np.asarray(phase, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != means.size or scales.shape != means.shape:
        raise RFFContractError("TRANSFORM_FEATURE_SHAPE_INVALID")
    if projection.ndim != 2 or projection.shape[0] != matrix.shape[1] or phase.shape != (projection.shape[1],):
        raise RFFContractError("RFF_PROJECTION_SHAPE_INVALID")
    if chunk_rows <= 0 or not np.isfinite(means).all() or not np.isfinite(scales).all() or np.any(scales <= 0):
        raise RFFContractError("TRANSFORM_PARAMETER_INVALID")
    if np.isinf(matrix).any():
        raise RFFContractError("FEATURE_INFINITY_FORBIDDEN")
    result = np.empty((matrix.shape[0], projection.shape[1]), dtype=np.float64)
    multiplier = np.sqrt(2.0 / float(projection.shape[1]))
    for start in range(0, matrix.shape[0], chunk_rows):
        stop = min(start + chunk_rows, matrix.shape[0])
        block = np.array(matrix[start:stop], dtype=np.float64, copy=True)
        for column_index in range(block.shape[1]):
            column = block[:, column_index]
            missing = np.isnan(column)
            if missing.any():
                column[missing] = means[column_index]
            column -= means[column_index]
            column /= scales[column_index]
        projected = block @ projection
        del block
        projected += phase
        np.cos(projected, out=projected)
        projected *= multiplier
        if not np.isfinite(projected).all():
            raise RFFContractError("RFF_TRANSFORM_NONFINITE")
        result[start:stop] = projected
        del projected
    return result


def _validate_logistic_data(z: np.ndarray, y: np.ndarray, c: float) -> tuple[np.ndarray, np.ndarray]:
    features = np.asarray(z, dtype=np.float64)
    labels = np.asarray(y, dtype=np.float64)
    if features.ndim != 2 or features.shape[0] == 0 or features.shape[1] == 0:
        raise RFFContractError("LOGISTIC_FEATURE_SHAPE_INVALID")
    if labels.shape != (features.shape[0],):
        raise RFFContractError("LOGISTIC_LABEL_SHAPE_INVALID")
    if not np.isfinite(features).all() or not np.isfinite(labels).all():
        raise RFFContractError("LOGISTIC_NONFINITE_INPUT")
    if not np.isin(labels, (0.0, 1.0)).all():
        raise RFFContractError("LOGISTIC_LABELS_NOT_BINARY")
    if not np.isfinite(c) or c <= 0:
        raise RFFContractError("LOGISTIC_C_INVALID")
    return features, labels


def logistic_objective_and_gradient(
    theta: np.ndarray,
    z: np.ndarray,
    y: np.ndarray,
    *,
    c: float = LOGISTIC_C,
) -> tuple[float, np.ndarray]:
    """mean BCE + ||w||²/(2*C*n), with an unpenalized intercept."""
    features, labels = _validate_logistic_data(z, y, c)
    parameters = np.asarray(theta, dtype=np.float64)
    if parameters.shape != (features.shape[1] + 1,) or not np.isfinite(parameters).all():
        raise RFFContractError("LOGISTIC_PARAMETER_SHAPE_OR_VALUE_INVALID")
    weights = parameters[:-1]
    intercept = float(parameters[-1])
    n_rows = float(labels.size)
    logits = features @ weights + intercept
    loss = float(np.mean(np.logaddexp(0.0, logits) - labels * logits))
    loss += float(np.dot(weights, weights) / (2.0 * c * n_rows))
    residual = expit(logits) - labels
    gradient_weights = (features.T @ residual) / n_rows
    gradient_weights += weights / (c * n_rows)
    gradient_intercept = float(np.mean(residual))
    gradient = np.empty_like(parameters)
    gradient[:-1] = gradient_weights
    gradient[-1] = gradient_intercept
    return loss, gradient


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not np.isfinite(number):
            return None
        return number
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "sk") and hasattr(value, "yk"):
        return {
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "n_corrs": int(getattr(value, "n_corrs", 0)),
            "sk": _jsonable(np.asarray(value.sk)),
            "yk": _jsonable(np.asarray(value.yk)),
            "rho": _jsonable(np.asarray(getattr(value, "rho", []))),
        }
    if hasattr(value, "__dict__"):
        return {"type": f"{type(value).__module__}.{type(value).__qualname__}", "state": _jsonable(vars(value))}
    raise RFFContractError(f"OPTIMIZER_RESULT_FIELD_NOT_SERIALIZABLE:{type(value).__qualname__}")


def serialize_optimizer_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Persist every result field, including the finite limited-memory inverse Hessian state."""
    return {str(key): _jsonable(value) for key, value in result.items()}


def fit_logistic(z: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float, dict[str, Any]]:
    features, labels = _validate_logistic_data(z, y, LOGISTIC_C)
    initial = np.zeros(features.shape[1] + 1, dtype=np.float64)
    # This one call consumes the candidate fit budget even if the optimizer
    # returns failure or does not converge.
    result = minimize(
        logistic_objective_and_gradient,
        initial,
        args=(features, labels),
        method="L-BFGS-B",
        jac=True,
        options=dict(L_BFGS_B_OPTIONS),
    )
    serialized = serialize_optimizer_result(result)
    if result.get("success") is not True:
        raise OptimizerNotConverged(serialized)
    parameters = np.asarray(result["x"], dtype=np.float64)
    if parameters.shape != initial.shape or not np.isfinite(parameters).all():
        raise RFFContractError("OPTIMIZER_PARAMETERS_INVALID")
    return parameters[:-1], float(parameters[-1]), serialized


def predict_full_eval(
    x_eval_scoreable: np.ndarray,
    means: np.ndarray,
    scales: np.ndarray,
    projection: np.ndarray,
    phase: np.ndarray,
    weights: np.ndarray,
    intercept: float,
    *,
    chunk_rows: int = TRANSFORM_CHUNK_ROWS,
) -> tuple[np.ndarray, np.ndarray]:
    """One public full-S prediction call with bounded internal RFF chunks."""
    matrix = np.asarray(x_eval_scoreable)
    coefficients = np.asarray(weights, dtype=np.float64)
    if coefficients.shape != (np.asarray(projection).shape[1],) or not np.isfinite(intercept):
        raise RFFContractError("PREDICTION_PARAMETER_SHAPE_INVALID")
    margins = np.empty(matrix.shape[0], dtype=np.float64)
    probabilities = np.empty(matrix.shape[0], dtype=np.float64)
    for start in range(0, matrix.shape[0], chunk_rows):
        stop = min(start + chunk_rows, matrix.shape[0])
        features = transform_rff(
            matrix[start:stop], means, scales, projection, phase,
            chunk_rows=max(1, stop - start),
        )
        block_margin = features @ coefficients + intercept
        margins[start:stop] = block_margin
        probabilities[start:stop] = expit(block_margin)
        del features, block_margin
    if not np.isfinite(margins).all() or not np.isfinite(probabilities).all():
        raise RFFContractError("PREDICTION_OUTPUT_NONFINITE")
    return margins, probabilities
