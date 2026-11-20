"""Server-owned execution and write/verify/commit sequence for V8."""
from __future__ import annotations

import json
import math
from pathlib import Path

from .validation import (
    FEATURE_COLUMNS, KEY_FIELDS, LR_PARAMS, OFFICIAL, RUN_A, SYNTHETIC, Rejected,
    canonical, digest, identity_digest, metrics, model_identity, require, rows_digest,
)


class RealExecutionHardGuard:
    """This zero-FIT release has no externally configurable unlock switch."""

    @staticmethod
    def assert_zero_fit_release():
        raise Rejected("ZERO_FIT_RELEASE_REAL_EXECUTION_HARD_GUARD")


class _SyntheticBackend:
    """Deterministic test objects with no sklearn or model deserialization."""

    def __init__(self):
        self.preprocessor = None

    def fit_preprocessor(self, rows):
        columns = list(zip(*(r["feature_vector_10"][:8] for r in rows)))
        means = [sum(col) / len(col) for col in columns]
        scales = [math.sqrt(sum((x - mean) ** 2 for x in col) / len(col))
                  for col, mean in zip(columns, means)]
        scales = [value if value > 0 else 1.0 for value in scales]
        self.preprocessor = {
            "n_features": 8, "mean": means, "scale": scales,
            "z_min": [min((x - mean) / scale for x in col) for col, mean, scale in zip(columns, means, scales)],
            "z_max": [max((x - mean) / scale for x in col) for col, mean, scale in zip(columns, means, scales)],
            "scope": SYNTHETIC,
        }

    def fit_model(self, rows, weights):
        require(self.preprocessor is not None and len(rows) == len(weights), "STUB_TRAINING_SEQUENCE_INVALID")
        return [0.0] * 10, 0.0, [0, 1]

    def predict(self, rows):
        return [0.25] * len(rows)


class _OfficialBackend:
    """Real model API access bound to the service's admitted one-use execution permit."""

    def __init__(self, authority, transaction_id, permit):
        from .authority import Authority
        require(type(authority) is Authority and authority.anchor["scope"] == OFFICIAL,
                "OFFICIAL_AUTHORITY_CONTEXT_REQUIRED")
        authority.assert_execution_permit(transaction_id, permit)
        self.authority = authority
        self.transaction_id = transaction_id
        self.permit = permit
        self.scaler = None
        self.classifier = None
        self.preprocessor = None
        self._verify_runtime()
        self._data = self.authority._prepared()["units"]["F1_RETRY"]

    def _verify_runtime(self):
        import inspect
        import sklearn
        import sklearn.linear_model._logistic as logistic_source
        import sklearn.preprocessing._data as scaler_source
        from .official_inputs import SKLEARN_FILES
        self.authority.assert_execution_permit(self.transaction_id, self.permit)
        prepared = self.authority._prepared()
        require(sklearn.__version__ == "1.8.0", "REAL_SKLEARN_VERSION_MISMATCH")
        for relative, module in (("sklearn/linear_model/_logistic.py", logistic_source),
                                 ("sklearn/preprocessing/_data.py", scaler_source)):
            actual = Path(inspect.getfile(module)).resolve()
            require(digest(actual.read_bytes()) == SKLEARN_FILES[relative] and
                    prepared["source_paths"].get("deps/" + relative) == str(actual),
                    "REAL_IMPORTED_SKLEARN_SOURCE_MISMATCH")

    def _claim(self, stage):
        self._verify_runtime()
        self.authority.claim_real_call(self.transaction_id, stage, self.permit)

    def fit_preprocessor(self, rows):
        require(rows == self._data["train_rows"], "REAL_TRAIN_INPUT_CHANGED")
        import numpy as np
        from sklearn.preprocessing import StandardScaler
        self._claim("preprocessing_fit")
        continuous = np.asarray([r["feature_vector_10"][:8] for r in rows], dtype=np.float64)
        self.scaler = StandardScaler(copy=True, with_mean=True, with_std=True)
        scaled = self.scaler.fit_transform(continuous)
        self.authority.real_call_returned(self.transaction_id, "preprocessing_fit")
        self.preprocessor = {
            "n_features": 8, "mean": self.scaler.mean_.tolist(), "scale": self.scaler.scale_.tolist(),
            "z_min": scaled.min(axis=0).tolist(), "z_max": scaled.max(axis=0).tolist(),
        }

    def _transform(self, rows):
        self.authority.assert_execution_permit(self.transaction_id, self.permit)
        require(self.scaler is not None, "PREPROCESSOR_NOT_FITTED")
        import numpy as np
        raw = np.asarray([r["feature_vector_10"] for r in rows], dtype=np.float64)
        continuous = self.scaler.transform(raw[:, :8])
        clipped = np.clip(continuous, self.preprocessor["z_min"], self.preprocessor["z_max"])
        return np.column_stack((clipped, raw[:, 8:]))

    def fit_model(self, rows, weights):
        require(rows == self._data["train_rows"] and weights == self._data["train_weights"], "REAL_TRAIN_OR_WEIGHT_CHANGED")
        import numpy as np
        import inspect
        from sklearn.linear_model import LogisticRegression
        self._claim("model_fit")
        l2_parameter = {"l1_ratio": 0.0} if "l1_ratio" in inspect.signature(LogisticRegression).parameters else {"penalty": "l2"}
        self.classifier = LogisticRegression(**l2_parameter, **LR_PARAMS)
        self.classifier.fit(self._transform(rows), [r["pb15_label"] for r in rows], sample_weight=weights)
        self.authority.real_call_returned(self.transaction_id, "model_fit")
        require(bool(np.all(self.classifier.n_iter_ < LR_PARAMS["max_iter"])), "OFFICIAL_MODEL_NONCONVERGED")
        return self.classifier.coef_[0].tolist(), float(self.classifier.intercept_[0]), self.classifier.classes_.tolist()

    def predict(self, rows):
        require(rows == self._data["holdout_rows"], "REAL_HOLDOUT_INPUT_CHANGED")
        self._claim("model_api")
        probabilities = self.classifier.predict_proba(self._transform(rows))
        self.authority.real_call_returned(self.transaction_id, "model_api", int(probabilities.shape[0]))
        return probabilities[:, list(self.classifier.classes_).index(1)].tolist()


def run_staged_unit(authority, transaction_id: str, *, _permit=None):
    """Only called by Authority.execute after atomic lease/state admission.

    There is no caller-controlled factory. The authority verifies the actual
    prepared document, derives its own rows, owns STARTs, and commits output.
    """
    authority.assert_execution_permit(transaction_id, _permit)
    prepared = authority._prepared()
    with authority.db() as connection:
        transaction = connection.execute("SELECT unit,state FROM transactions WHERE transaction_id=?", (transaction_id,)).fetchone()
        require(transaction is not None and transaction["state"] == "STARTED", "EXECUTION_CONTEXT_NOT_ADMITTED")
        unit = transaction["unit"]
    require(authority.anchor["scope"] == prepared["scope"], "EXECUTION_SCOPE_MISMATCH")
    if prepared["scope"] == OFFICIAL:
        backend = _OfficialBackend(authority, transaction_id, _permit)
    else:
        require(prepared["scope"] == SYNTHETIC, "EXECUTION_TRUST_DOMAIN_INVALID")
        backend = _SyntheticBackend()
    data = prepared["units"][unit]
    if prepared["scope"] == SYNTHETIC:
        authority.start_stage(transaction_id, "preprocessing_fit")
    backend.fit_preprocessor(data["train_rows"])
    if prepared["scope"] == SYNTHETIC:
        authority.record_stub(transaction_id, "preprocessing_fit")
        authority.start_stage(transaction_id, "model_fit")
    coefficients, intercept, classes = backend.fit_model(data["train_rows"], data["train_weights"])
    if prepared["scope"] == SYNTHETIC:
        authority.record_stub(transaction_id, "model_fit")
    prediction_calls = 0
    probabilities = []
    if unit == "F1_RETRY":
        if prepared["scope"] == SYNTHETIC:
            authority.start_stage(transaction_id, "model_api")
        probabilities = backend.predict(data["holdout_rows"])
        if prepared["scope"] == SYNTHETIC:
            authority.record_stub(transaction_id, "model_api")
        prediction_calls = 1
    else:
        require(unit == "FINAL_DEV" and not data["holdout_rows"], "FINAL_DEV_PREDICTION_FORBIDDEN")
    model = {
        "scope": prepared["scope"], "unit": unit, "execution_identity_sha256": RUN_A,
        "authority_id": authority.anchor["authority_id"], "transaction_id": transaction_id,
        "identity_sha256": identity_digest(prepared), "rows_sha256": rows_digest(prepared),
        "source_files": prepared["source_files"], "feature_columns": list(FEATURE_COLUMNS),
        "lr_params": LR_PARAMS, "prediction_api_calls": prediction_calls,
        "preprocessor": backend.preprocessor, "coefficients": coefficients, "intercept": intercept,
        "classes": classes,
    }
    fault = authority.anchor["test_fault"]
    if fault == "wrong_model_identity":
        model["execution_identity_sha256"] = "WRONG_IDENTITY_SYNTHETIC_TEST_ONLY"
    if fault == "missing_model_weights":
        model.pop("coefficients")
        model.pop("preprocessor")
    model["model_identity_sha256"] = model_identity(model)
    rows = []
    for truth, probability in zip(data["holdout_rows"], probabilities):
        rows.append({
            **{key: truth[key] for key in KEY_FIELDS},
            "scope": prepared["scope"], "transaction_id": transaction_id,
            "model_identity_sha256": model["model_identity_sha256"],
            "y_true": truth["pb15_label"], "p_pred": probability,
        })
    if fault == "second_row_identity" and len(rows) >= 2:
        rows[1]["parent_id"] = "WRONG_SECOND_ROW_SYNTHETIC_TEST_ONLY"
    outputs = {"model.json": canonical(model)}
    if unit == "F1_RETRY":
        outputs["predictions.jsonl"] = b"".join(canonical(row) + b"\n" for row in rows)
        outputs["metrics.json"] = canonical(metrics(rows))
    directory = authority.root / "outputs" / transaction_id
    require(not directory.exists(), "OUTPUT_ALREADY_STAGED_NO_RETRY")
    from .authority import write_once
    written = {}
    for name, raw in outputs.items():
        written[name] = write_once(directory / name, raw)
    if fault == "missing_output":
        (directory / "model.json").unlink()
    if fault == "corrupt_output":
        (directory / "model.json").write_bytes(b"CORRUPTED_SYNTHETIC_TEST_ONLY")
    if fault == "wrong_sha":
        written["model.json"]["sha256"] = "0" * 64
    authority.stage_output(transaction_id)
    return authority.commit_output(transaction_id, written)
