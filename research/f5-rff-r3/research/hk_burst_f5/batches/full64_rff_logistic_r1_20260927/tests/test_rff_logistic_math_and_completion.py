from __future__ import annotations

import numpy as np
import pytest

from rff_logistic_core import (
    L_BFGS_B_OPTIONS,
    logistic_objective_and_gradient,
    fit_logistic,
    fit_preprocessor,
    transform_rff,
)


def test_objective_gradient_matches_finite_difference():
    z = np.asarray([[0.2, -0.4], [1.1, 0.3], [-0.7, 0.8]], dtype=np.float64)
    y = np.asarray([1.0, 0.0, 1.0], dtype=np.float64)
    theta = np.asarray([0.15, -0.23, 0.07], dtype=np.float64)
    value, gradient = logistic_objective_and_gradient(theta, z, y, c=1.0)
    eps = 1e-6
    numeric = np.empty_like(theta)
    for index in range(theta.size):
        delta = np.zeros_like(theta)
        delta[index] = eps
        high = logistic_objective_and_gradient(theta + delta, z, y, c=1.0)[0]
        low = logistic_objective_and_gradient(theta - delta, z, y, c=1.0)[0]
        numeric[index] = (high - low) / (2 * eps)
    assert np.isfinite(value)
    np.testing.assert_allclose(gradient, numeric, rtol=2e-6, atol=2e-8)


def test_train_only_preprocessing_and_rff_are_deterministic():
    train = np.asarray([[1.0, np.nan, 4.0], [3.0, np.nan, 4.0], [5.0, np.nan, 4.0]])
    means, scales = fit_preprocessor(train)
    np.testing.assert_array_equal(means, [3.0, 0.0, 4.0])
    np.testing.assert_array_equal(scales, [np.sqrt(8.0 / 3.0), 1.0, 1.0])
    projection_1, phase_1 = make_test_projection(3)
    projection_2, phase_2 = make_test_projection(3)
    transformed_1 = transform_rff(train, means, scales, projection_1, phase_1, chunk_rows=2)
    transformed_2 = transform_rff(train, means, scales, projection_2, phase_2, chunk_rows=1)
    np.testing.assert_array_equal(transformed_1, transformed_2)
    assert transformed_1.shape == (3, projection_1.shape[1])
    assert np.isfinite(transformed_1).all()


def make_test_projection(features: int):
    rng = np.random.RandomState(42)
    projection = rng.normal(scale=np.sqrt(2.0 / 64.0), size=(features, 8))
    phase = rng.uniform(0.0, 2.0 * np.pi, size=8)
    return projection, phase


def test_lbfgsb_contract_options_and_nonconvergence_fail_closed(monkeypatch):
    import rff_logistic_core as core

    assert L_BFGS_B_OPTIONS == {
        "ftol": 2.220446049250313e-9,
        "gtol": 1e-5,
        "maxiter": 200,
        "maxfun": 5000,
        "maxls": 20,
        "maxcor": 10,
    }
    captured = {}

    class OptimizerResult(dict):
        __getattr__ = dict.__getitem__

    def fake_minimize(fun, x0, *, args, method, jac, options):
        captured.update(method=method, jac=jac, options=options)
        value, grad = fun(x0, *args)
        return OptimizerResult(
            x=np.array(x0, copy=True), fun=value, jac=grad, nit=1, nfev=1,
            njev=1, status=1, success=False, message="STOP: ITERATION LIMIT",
            hess_inv=None,
        )

    monkeypatch.setattr(core, "minimize", fake_minimize)
    z = np.asarray([[0.0, 1.0], [1.0, 0.0]], dtype=np.float64)
    y = np.asarray([0.0, 1.0], dtype=np.float64)
    with pytest.raises(core.OptimizerNotConverged):
        fit_logistic(z, y)
    assert captured == {
        "method": "L-BFGS-B",
        "jac": True,
        "options": L_BFGS_B_OPTIONS,
    }
