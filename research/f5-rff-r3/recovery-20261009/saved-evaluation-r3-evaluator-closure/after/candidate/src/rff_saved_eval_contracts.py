"""RFF saved-evaluation identities and metadata preparation; never a producer.

Preparation opens source, JSON metadata and the registry prefix only. Score,
Top3, label and model rows are not opened here. A prepared binding is unsigned;
the native controller must independently review it and issue a separate release.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

ROUTE = "F5_FULL64_RFF_LOGISTIC_R1_20260927"
CANDIDATE = ROUTE + "_RESUME_20260928_01"
SAFETY = {"research_only": True, "production_allowed": False,
          "buy_gate_updated": False, "orders_sent": False}
ZERO_AUTHORIZATIONS = ("fit_calls_authorized", "predict_calls_authorized",
    "control_fit_calls_authorized", "control_predict_calls_authorized",
    "calibrator_fit_calls_authorized", "model_load_calls_authorized")
ZERO_COUNTS = {"fit_calls": 0, "real_fit_returned_count": 0, "predict_calls": 0,
    "control_fit_calls": 0, "control_predict_calls": 0, "calibrator_fit_calls": 0,
    "model_load_calls": 0, "fit_call_entered": False, "candidate_model_loaded": False}
CONTROLS = ("FROZEN_UNWEIGHTED_PLUS_PATH", "FROZEN_BASE34")
EVALUATION = {"year": 2024, "grid_rows": 169986, "scoreable_rows": 120084,
              "sessions": 246, "selection_slots": 738, "known_positive_denominator": 126}
# Complete file-byte SHA256 values; registry event identities are separate below.
PINS = {
    "accepted_worker": "3ea10757a81207147e5cfb9e68e69750a0579786153e7ce58ccf342a3184058c",
    "experiment_contract": "e6c1509955730a032d183563d6ffcf2501a587dd5734426f35fc59b222491135",
    "candidate_binding": "efe96e1d1046d074f545d7d53501d7281d2fad2e24b0a8f9f1ad9199f06f44d7",
    "candidate_spec": "ec28511f6e2d8567635ed0d7bd5d0a92805e7310e08f944bd1e854a5b99ab3fc",
    "prediction_seal": "4fc18f9ae2cd47d3a1a23adaadd2ddcc5db9aa97b60a1758d78f2b497cdc8bfa",
    "candidate_start": "0292f37c00181b3447d0cda65f0b24096e9100ace35fb024ff5f579248e64a03",
    "candidate_terminal": "c8dc367a7acf7196c4951074759e8c8015c071d6c2d7e6cf8b3afd3bf01f6ca1",
    "candidate_scores": "3b87a52e5b2d2df88e3091a2c8e3b5262f809bf6323363a31047223f91bdc006",
    "candidate_top3": "273504cc6152dedf2f6f88ae6fb6af5598af84340b2e954241d7b6ff6f63a78e",
    "FROZEN_BASE34_scores": "b3c1e4dec4f98f84aad466291bb9968aaa1bdc5993892166c0693f54e956edcd",
    "FROZEN_BASE34_top3": "182f95feab6ac840c03cb63772e10f918aa1ea5b82c34b36036dd2aded25da40",
    "FROZEN_UNWEIGHTED_PLUS_PATH_scores": "5e0335ce334b4deda2f88705cde6601adf62c6c0e24a0bdb826d2858001a99cc",
    "FROZEN_UNWEIGHTED_PLUS_PATH_top3": "c3efc891e6d4432e0d97d64d38500bd61d2ff5fef853d7aa0cd005f5af3a625b",
    "score_aware_metrics": "fc93d6225c75b633981508a18c428e7649122571c7d897264d0b7da1e591eb8c",
    "frozen_metrics": "c8ffabf345069d64a82ac686e6747afda8c22433f1309eecdc999a7ad1eac763",
    "frozen_evaluator_manifest": "64fd0f7a5e3d646f7b5b184d44ca10576aab9db73772b3abb2cfceab36862a9b",
    "resource_tree": "9d0792a8e582d0345c83ddaf83a15612a5629b5f0460833b4715068324ff2752",
    "execution_guard": "85929366a7b018480085c02f80edd312f7f47de94bab5c32982d4e8637d7d7e0",
    "registry_adapter": "8596f2a20c165b5fbc2b92a597cb3e1177f6e40bfefac62753b40b3c7daae17f",
    "builder": "df4bfc89fa5487966a8c7e1c1c50832e140339c2ccda3a02a9a59e5aaaeb58cf",
    "validator": "80e49d05d13f33ee7e2cb8d4d10cae0e297bcdf5b113ff857d3bd141dea0f438",
}
CANDIDATE_EVENT_SHA256 = {
    "start": "69a41b317075cfcb21c26133401e19b8af7a435185c87d5f4cf76f7b2e24d9af",
    "terminal": "5fe5704e4fb63a00e1802a14ba7e09f41985342a89e4f0c301793991b80ff0cf",
}
SOURCE_NAMES = ("rff_saved_eval_contracts", "rff_saved_eval_frames",
                "rff_saved_eval_registration", "rff_saved_eval_worker",
                "run_rff_saved_evaluation")
INPUT_NAMES = {"candidate_scores", "candidate_top3", "eval_truth", "eval_calendar",
               *(f"{arm}_{kind}" for arm in CONTROLS for kind in ("scores", "top3"))}
_EXPERIMENT_RELATIVE = Path("research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927/contracts/EXPERIMENT_CONTRACT.json")
_SCORE_AWARE_RELATIVE = Path("research/hk_burst_f5/batches/full64_xendcg_r1_20260924/src/score_aware_metrics.py")
_POLICY_NAME = "EXPERIMENT_REGISTRY_APPEND_COMPATIBILITY_POLICY_V1.json"
_FROZEN_MODULES = {
    "frozen_package_init": ("spike5", "spike5/__init__.py"),
    "frozen_common": ("spike5.common", "spike5/common.py"),
    "frozen_features": ("spike5.features", "spike5/features.py"),
    "frozen_settings": ("spike5.settings", "spike5/settings.py"),
    "frozen_metrics": ("spike5.metrics", "spike5/metrics.py"),
}
_FROZEN_CONFIGS = {"frozen_base_features": "config/base_features.json",
                   "frozen_contract": "config/contract.json"}


class SavedEvaluationError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def plain_path(path: str | Path, *, exists: bool = True) -> Path:
    p = Path(path).expanduser().absolute()
    # Reject aliases in every directory component; inputs cannot be rebound by
    # changing a symlink after the metadata check.
    if any(q.is_symlink() for q in (p, *p.parents)):
        raise SavedEvaluationError(f"SYMLINK_PATH_FORBIDDEN:{p}")
    if exists and not p.is_file():
        raise SavedEvaluationError(f"BOUND_FILE_MISSING:{p}")
    return p.resolve(strict=exists)


def file_record(path: str | Path, expected_sha: str | None = None) -> dict[str, Any]:
    p = plain_path(path)
    digest = sha256_file(p)
    if expected_sha is not None and digest != expected_sha:
        raise SavedEvaluationError(f"BOUND_FILE_SHA_MISMATCH:{p}:{digest}:{expected_sha}")
    return {"path": str(p), "sha256": digest, "bytes": p.stat().st_size}


def checked_read(record: Mapping[str, Any], *, name: str = "snapshot") -> bytes:
    p = plain_path(record["path"])
    raw = p.read_bytes()
    if sha256_bytes(raw) != record.get("sha256"):
        raise SavedEvaluationError(f"BOUND_SNAPSHOT_SHA_MISMATCH:{name}:{p}")
    if "bytes" in record and len(raw) != record["bytes"]:
        raise SavedEvaluationError(f"BOUND_SNAPSHOT_SIZE_MISMATCH:{name}:{p}")
    return raw


def json_object(raw: bytes, *, name: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise SavedEvaluationError(f"JSON_OBJECT_REQUIRED:{name}")
    return value


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> str:
    p = plain_path(path, exists=False)
    p.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(value) + b"\n"
    fd, tempname = tempfile.mkstemp(prefix=".rff-saved-eval-", dir=p.parent)
    temporary = Path(tempname)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, p)  # atomic create; an existing receipt is never replaced
        dirfd = os.open(p.parent, os.O_RDONLY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_bytes(raw)


def load_bound_module(record: Mapping[str, Any], name: str, *, package: bool = False):
    raw = checked_read(record, name=name)
    path = Path(record["path"])
    existing = sys.modules.get(name)
    if existing is not None:
        if (Path(str(getattr(existing, "__file__", ""))).resolve() != path.resolve()
                or getattr(existing, "__rff_source_sha256__", None) != record["sha256"]):
            raise SavedEvaluationError(f"CACHED_MODULE_IDENTITY_MISMATCH:{name}")
        return existing
    spec = importlib.util.spec_from_file_location(name, path,
        submodule_search_locations=[str(path.parent)] if package else None)
    if spec is None:
        raise SavedEvaluationError(f"MODULE_SPEC_FAILED:{name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        exec(compile(raw, str(path), "exec"), module.__dict__)
        module.__rff_source_sha256__ = record["sha256"]
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def verify_sources(binding: Mapping[str, Any]) -> None:
    if sha256_bytes(canonical_bytes(binding["code_files"])) != binding["code_sha256"]:
        raise SavedEvaluationError("CODE_MANIFEST_SHA_MISMATCH")
    for category in ("code_files", "executable_helpers", "official_helpers", "metadata_files"):
        for name, record in binding[category].items():
            checked_read(record, name=f"{category}:{name}")


def _frozen_evaluator_manifest():
    # This historical manifest is authenticated by the separately retained
    # Mac-fixed package identity receipt. Never promote current file hashes.
    path = Path(__file__).resolve().parent.parent / "contracts/FROZEN_EVALUATOR_SOURCE_MANIFEST.json"
    record = file_record(path, PINS["frozen_evaluator_manifest"])
    document = json_object(checked_read(record, name="frozen_evaluator_manifest"),
                           name="frozen_evaluator_manifest")
    if (document.get("schema") != "HK_SPIKE_F5_MAC_FIXED_SOURCE_MANIFEST_V1"
            or document.get("identity_kind") != "MAC_FIXED_SOURCE_ARCHIVE"):
        raise SavedEvaluationError("FROZEN_EVALUATOR_HISTORICAL_MANIFEST_REQUIRED")
    files = {item["path"]: item for item in document["files"]}
    if len(files) != len(document["files"]):
        raise SavedEvaluationError("FROZEN_EVALUATOR_HISTORICAL_PATH_DUPLICATE")
    return record, files


def bind_frozen_evaluator(metrics_path: str | Path):
    """Read only the seven historically identified evaluator source/config files."""
    metrics = plain_path(metrics_path)
    if metrics.name != "metrics.py" or metrics.parent.name != "spike5":
        raise SavedEvaluationError("FROZEN_EVALUATOR_PACKAGE_LAYOUT_MISMATCH")
    root = metrics.parent.parent
    manifest, historical = _frozen_evaluator_manifest()

    def identified(relative):
        expected = historical[relative]
        record = file_record(root / relative, expected["sha256"])
        if record["bytes"] != expected["bytes"]:
            raise SavedEvaluationError(f"FROZEN_EVALUATOR_HISTORICAL_SIZE_MISMATCH:{relative}")
        return record

    helpers = {key: identified(relative) for key, (_, relative) in _FROZEN_MODULES.items()}
    metadata = {key: identified(relative) for key, relative in _FROZEN_CONFIGS.items()}
    metadata["frozen_evaluator_manifest"] = manifest
    return helpers, metadata


def validate_frozen_evaluator(binding: Mapping[str, Any]) -> dict[str, Any]:
    """Validate paths, bytes and historical SHA before executing any package code."""
    helpers, metadata = binding.get("executable_helpers", {}), binding.get("metadata_files", {})
    for category, keys in ((helpers, _FROZEN_MODULES),
                           (metadata, (*_FROZEN_CONFIGS, "frozen_evaluator_manifest"))):
        for key in keys:
            if not isinstance(category.get(key), Mapping):
                raise SavedEvaluationError(f"FROZEN_EVALUATOR_DEPENDENCY_MISSING:{key}")
    metrics = plain_path(helpers["frozen_metrics"]["path"])
    if metrics.name != "metrics.py" or metrics.parent.name != "spike5":
        raise SavedEvaluationError("FROZEN_EVALUATOR_PACKAGE_LAYOUT_MISMATCH")
    root = metrics.parent.parent
    manifest, historical = _frozen_evaluator_manifest()
    if canonical_bytes(metadata["frozen_evaluator_manifest"]) != canonical_bytes(manifest):
        raise SavedEvaluationError("FROZEN_EVALUATOR_HISTORICAL_MANIFEST_IDENTITY_MISMATCH")

    def validated(category, key, relative):
        record, expected = category[key], historical[relative]
        path = root / relative
        if record.get("path") != str(path) or plain_path(record["path"]) != path:
            raise SavedEvaluationError(f"FROZEN_EVALUATOR_PATH_MISMATCH:{key}")
        if (record.get("sha256") != expected["sha256"]
                or type(record.get("bytes")) is not int or record["bytes"] != expected["bytes"]):
            raise SavedEvaluationError(f"FROZEN_EVALUATOR_HISTORICAL_IDENTITY_MISMATCH:{key}")
        checked_read(record, name=key)
        return record

    modules = {name: validated(helpers, key, relative)
               for key, (name, relative) in _FROZEN_MODULES.items()}
    configs = {str(root / relative): validated(metadata, key, relative)
               for key, relative in _FROZEN_CONFIGS.items()}
    closure = {"modules": modules, "configs": configs, "historical_manifest": manifest}
    return {"modules": modules, "configs": configs,
            "closure_sha256": sha256_bytes(canonical_bytes(closure))}


def validate_resources(value: Mapping[str, Any]) -> dict[str, Any]:
    keys = {"cpu_threads", "aggregate_process_tree_rss_bytes_max", "wall_seconds_max", "sample_seconds"}
    if set(value) != keys:
        raise SavedEvaluationError("EXPLICIT_RESOURCE_BOUNDS_REQUIRED_NO_HISTORICAL_DEFAULTS")
    for name in ("cpu_threads", "aggregate_process_tree_rss_bytes_max"):
        if type(value[name]) is not int or value[name] <= 0:
            raise SavedEvaluationError(f"RESOURCE_POSITIVE_INTEGER_REQUIRED:{name}")
    for name in ("wall_seconds_max", "sample_seconds"):
        if type(value[name]) not in (int, float) or not math.isfinite(value[name]) or value[name] <= 0:
            raise SavedEvaluationError(f"RESOURCE_POSITIVE_FINITE_REQUIRED:{name}")
    if value["sample_seconds"] > value["wall_seconds_max"]:
        raise SavedEvaluationError("RESOURCE_SAMPLE_EXCEEDS_WALL_BOUND")
    return dict(value)


def execution_spec(execution_id: str, resources: Mapping[str, Any]) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,160}", execution_id) or execution_id == CANDIDATE:
        raise SavedEvaluationError("NEW_EVALUATION_EXECUTION_ID_REQUIRED")
    return {"schema": "F5_RFF_SAVED_EVALUATION_RUN_SPEC_V1", "route_id": ROUTE,
        "execution_id": execution_id, "candidate_execution_id": CANDIDATE,
        **{key: 0 for key in ZERO_AUTHORIZATIONS},
        "evaluation_truth_decode_authorized": 1,
        "candidate_model_load_authorized": False, "automatic_retry": False,
        "evidence_ceiling": "DIRECTION_ONLY", "safety": dict(SAFETY),
        "resources": validate_resources(resources), "evaluation_contract": dict(EVALUATION),
        "experiment_contract_sha256": PINS["experiment_contract"],
        "accepted_worker_sha256": PINS["accepted_worker"],
        "historical_candidate_debits": {"fit": 1, "predict": 1, "truth_decode": 1},
        "historical_debits_reset": False}


def validate_execution_spec(spec: Mapping[str, Any]) -> None:
    expected = execution_spec(str(spec.get("execution_id", "")), spec.get("resources", {}))
    for key in ZERO_AUTHORIZATIONS:
        if type(spec.get(key)) is not int or spec[key] != 0:
            raise SavedEvaluationError(f"ZERO_AUTHORIZATION_REQUIRED:{key}")
    if canonical_bytes(dict(spec)) != canonical_bytes(expected):
        raise SavedEvaluationError("RFF_SAVED_EVALUATION_SPEC_SCOPE_MISMATCH")


def validate_new_paths(output: Path, trace: Path, candidate_root: Path,
                       inputs: Mapping[str, Mapping[str, Any]], *, require_new: bool) -> None:
    output = plain_path(output, exists=False)
    trace = plain_path(trace, exists=False)
    candidate = plain_path(candidate_root, exists=False)
    if output.is_relative_to(candidate) or candidate.is_relative_to(output):
        raise SavedEvaluationError("OUTPUT_OVERLAPS_CANDIDATE_ROOT")
    if trace.is_relative_to(output) or trace.is_relative_to(candidate):
        raise SavedEvaluationError("TRACE_OVERLAPS_CANDIDATE_OR_WORKER_OUTPUT")
    for name, record in inputs.items():
        p = plain_path(record["path"], exists=False)
        if p.is_relative_to(output) or trace == p or output.is_relative_to(p):
            raise SavedEvaluationError(f"MUTABLE_PATH_OVERLAPS_BOUND_INPUT:{name}")
        if p.exists() and trace.exists() and os.path.samefile(p, trace):
            raise SavedEvaluationError(f"TRACE_ALIASES_BOUND_INPUT:{name}")
    if require_new and (output.exists() or trace.exists()):
        raise SavedEvaluationError("OUTPUT_OR_TRACE_EXISTS_NO_REENTRY")


def _opaque_record(path: str | Path, digest: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
        raise SavedEvaluationError("ARTIFACT_SHA256_REQUIRED")
    # No content read, hash or size measurement. plain_path checks only path
    # identity (including symlinks); data artifacts need not exist to prepare.
    return {"path": str(plain_path(path, exists=False)), "sha256": digest}


def _old_native_records(old: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Preserve the two bindings enforced by rff_candidate_entry.py:351-385.

    The historical worker/source manifest is deliberately not replayed: PR5
    supplies a separately accepted worker and this is a new source manifest.
    """
    result = {}
    for name in ("native_runtime", "native_reference_contract"):
        path, digest = old.get(name + "_path"), old.get(name + "_sha256")
        mirror = old.get("executable_helpers", {}).get(name, {})
        if (not isinstance(path, str) or not Path(path).is_absolute()
                or mirror.get("path") != path):
            raise SavedEvaluationError(f"ORIGINAL_NATIVE_PATH_BINDING_MISMATCH:{name}")
        if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or mirror.get("sha256") != digest):
            raise SavedEvaluationError(f"ORIGINAL_NATIVE_SHA_BINDING_MISMATCH:{name}")
        result[name] = file_record(path, digest)
    return result


def _declared_frozen_metrics_path(record: Mapping[str, Any]) -> Path:
    """Read only the pinned helper's two literal path assignments, without import.

    score_aware_metrics.py:20-25 uses Path(literal) and path / literal. This
    intentionally supports only those named assignments and that grammar;
    evaluator functions and the accepted join helper are never inspected here.
    """
    tree = ast.parse(checked_read(record, name="score_aware_metrics"), filename=record["path"])
    values = {}

    def path_value(node):
        if isinstance(node, ast.Name) and node.id == "F5_SOURCE_ROOT" and node.id in values:
            return values[node.id]
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path"
                and len(node.args) == 1 and not node.keywords
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            return Path(node.args[0].value)
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
                and isinstance(node.right, ast.Constant) and isinstance(node.right.value, str)):
            return path_value(node.left) / node.right.value
        raise SavedEvaluationError("FROZEN_METRICS_PATH_LITERAL_BINDING_REQUIRED")

    for statement in tree.body:
        if (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                and statement.targets[0].id in ("F5_SOURCE_ROOT", "FROZEN_METRICS_PATH")):
            name = statement.targets[0].id
            if name in values:
                raise SavedEvaluationError("FROZEN_METRICS_PATH_DUPLICATE_BINDING")
            values[name] = path_value(statement.value)
    path = values.get("FROZEN_METRICS_PATH")
    if path is None or set(values) != {"F5_SOURCE_ROOT", "FROZEN_METRICS_PATH"} or not path.is_absolute():
        raise SavedEvaluationError("FROZEN_METRICS_PATH_LITERAL_BINDING_REQUIRED")
    return plain_path(path, exists=False)


def _append_policy_path(validator_record: Mapping[str, Any]) -> Path:
    # Exactly the implicit dependency used at import by the pinned validator.
    return plain_path(validator_record["path"]).parents[1] / "contracts" / _POLICY_NAME


def _require_reference(record: Mapping[str, Any], path: str | Path, digest: str,
                       code: str) -> None:
    expected = _opaque_record(path, digest)
    if any(record.get(key) != expected[key] for key in ("path", "sha256")):
        raise SavedEvaluationError(code)


def _validate_original_evaluation_scope(scope: Mapping[str, Any]) -> None:
    # Issue #33 and the original worker require the five counters. The exposed
    # 2024 scope is fixed by the pinned experiment contract; historical metadata
    # need not grow a new "year" key to be usable without mutation.
    for name, expected in EVALUATION.items():
        if name == "year" and name not in scope:
            continue
        if canonical_bytes(scope.get(name)) != canonical_bytes(expected):
            raise SavedEvaluationError(f"ORIGINAL_EVALUATION_SCOPE_MISMATCH:{name}")


def _validate_frozen_dependencies(binding: Mapping[str, Any]) -> None:
    """Cross-bind metadata using the immutable candidate and original producers.

    Only source and JSON metadata are opened. Data records remain opaque until
    the new owner has committed its durable RUN_STARTED.
    """
    metadata, helpers, official, inputs = (binding[key] for key in
        ("metadata_files", "executable_helpers", "official_helpers", "input_files"))
    old = json_object(checked_read(metadata["candidate_binding"]), name="candidate_binding")
    old_spec = json_object(checked_read(metadata["candidate_spec"]), name="candidate_spec")
    if (old.get("route_id") != ROUTE or old.get("execution_id") != CANDIDATE
            or old.get("input_binding_path") != metadata["candidate_binding"]["path"]):
        raise SavedEvaluationError("ORIGINAL_CANDIDATE_IDENTITY_MISMATCH")
    _require_reference(metadata["candidate_spec"], old["run_spec_path"], old["run_spec_sha256"],
                       "ORIGINAL_CANDIDATE_SPEC_BINDING_MISMATCH")
    if old_spec.get("route_id") != ROUTE or old_spec.get("execution_id") != CANDIDATE:
        raise SavedEvaluationError("ORIGINAL_CANDIDATE_SPEC_IDENTITY_MISMATCH")
    contract_record = metadata["experiment_contract"]
    _require_reference(contract_record, old["experiment_contract_path"], old["experiment_contract_sha256"],
                       "ORIGINAL_EXPERIMENT_CONTRACT_BINDING_MISMATCH")
    if old_spec.get("experiment_contract_sha256") != contract_record["sha256"]:
        raise SavedEvaluationError("ORIGINAL_SPEC_EXPERIMENT_CONTRACT_MISMATCH")
    contract = json_object(checked_read(contract_record), name="experiment_contract")
    if canonical_bytes(old_spec.get("decision_gates")) != canonical_bytes(contract["decision_gates"]):
        raise SavedEvaluationError("ORIGINAL_DECISION_GATES_CHANGED")
    _validate_original_evaluation_scope(old["evaluation_contract"])
    original_output = plain_path(old["output_root"], exists=False)
    if binding["candidate_output_root"] != str(original_output):
        raise SavedEvaluationError("OLD_CANDIDATE_OUTPUT_ROOT_MISMATCH")
    for name, filename in (("candidate_scores", "CANDIDATE_SCORES.csv.gz"),
                           ("candidate_top3", "CANDIDATE_TOP3.csv.gz")):
        _require_reference(inputs[name], original_output / filename, PINS[name],
                           f"ORIGINAL_CANDIDATE_ARTIFACT_PATH_OR_SHA_MISMATCH:{name}")
    for alias, original_name in (("eval_truth", "eval_meta.csv.gz"), ("eval_calendar", "eval_calendar.csv.gz")):
        original = old["input_files"][original_name]
        _require_reference(inputs[alias], original["path"], original["sha256"],
                           f"OLD_CANDIDATE_EVALUATION_INPUT_MISMATCH:{alias}")
    for arm in CONTROLS:
        original = old["baseline_artifacts"][arm]
        for kind in ("scores", "top3"):
            _require_reference(inputs[f"{arm}_{kind}"], original[f"{kind}_path"], original[f"{kind}_sha256"],
                               f"OLD_CONTROL_PATH_OR_SHA_CHANGED:{arm}:{kind}")
    for name, path in (("prediction_seal", original_output / "PREDICTION_SEALED_BEFORE_EVAL_TRUTH_READ.json"),
                       ("candidate_start", old["start_receipt_path"]),
                       ("candidate_terminal", original_output / "CANDIDATE_TERMINAL_RECEIPT.json")):
        _require_reference(metadata[name], path, PINS[name], f"ORIGINAL_METADATA_PATH_MISMATCH:{name}")
    seal = json_object(checked_read(metadata["prediction_seal"]), name="prediction_seal")
    validate_seal(seal, EVALUATION, CANDIDATE)
    for name in ("candidate_scores", "candidate_top3"):
        if seal.get(name + "_sha256") != inputs[name]["sha256"]:
            raise SavedEvaluationError(f"PREDICTION_SEAL_ARTIFACT_SHA_MISMATCH:{name}")
    start = json_object(checked_read(metadata["candidate_start"]), name="candidate_start")
    terminal = json_object(checked_read(metadata["candidate_terminal"]), name="candidate_terminal")
    if (start.get("execution_id") != CANDIDATE or start.get("route_id") != ROUTE
            or start.get("run_spec_sha256") != metadata["candidate_spec"]["sha256"]
            or start.get("input_binding_sha256") != metadata["candidate_binding"]["sha256"]
            or start.get("source_code_sha256") != old["code_sha256"]
            or terminal.get("execution_id") != CANDIDATE
            or terminal.get("start_receipt_sha256") != metadata["candidate_start"]["sha256"]):
        raise SavedEvaluationError("ORIGINAL_RECEIPT_CHAIN_IDENTITY_MISMATCH")
    if start.get("start_event_sha256") != CANDIDATE_EVENT_SHA256["start"]:
        raise SavedEvaluationError("ORIGINAL_START_EVENT_SHA_MISMATCH")
    if terminal.get("terminal_event_sha256") != CANDIDATE_EVENT_SHA256["terminal"]:
        raise SavedEvaluationError("ORIGINAL_TERMINAL_EVENT_SHA_MISMATCH")

    native = _old_native_records(old)
    for name, record in (("native_runtime", helpers["native_runtime"]),
                         ("native_reference_contract", metadata["native_reference"])):
        _require_reference(record, native[name]["path"], native[name]["sha256"],
                           f"ORIGINAL_NATIVE_REFERENCE_BINDING_MISMATCH:{name}")
    reference = json_object(checked_read(metadata["native_reference"]), name="native_reference")
    if (reference.get("schema") != "F5_FULL64_RFF_NATIVE_REFERENCE_RUNTIME_V1"
            or reference.get("route_id") != ROUTE):
        raise SavedEvaluationError("ORIGINAL_NATIVE_REFERENCE_IDENTITY_MISMATCH")
    runtime = reference["runtime_contract"]
    _require_reference(metadata["native_runtime_contract"], runtime["path"], runtime["sha256"],
                       "NATIVE_RUNTIME_CONTRACT_REFERENCE_MISMATCH")
    # SOURCE_MAP.json ties these declarations to the same frozen candidate
    # binding. Validate their metadata, without importing its historical code.
    if (old["runtime_contract_path"] != runtime["path"]
            or ("runtime_contract_sha256" in old and old["runtime_contract_sha256"] != runtime["sha256"])):
        raise SavedEvaluationError("ORIGINAL_RUNTIME_CONTRACT_BINDING_MISMATCH")
    _require_reference(old["executable_helpers"]["runtime_contract"], runtime["path"], runtime["sha256"],
                       "ORIGINAL_RUNTIME_CONTRACT_BINDING_MISMATCH")
    for name, record in official.items():
        original = old["official_helpers"][name]
        _require_reference(record, original["path"], original["sha256"],
                           f"ORIGINAL_OFFICIAL_HELPER_BINDING_MISMATCH:{name}")
    _require_reference(helpers["resource_tree"], old["resource_tree_path"], PINS["resource_tree"],
                       "RESOURCE_TREE_PATH_BINDING_MISMATCH")
    contract_path = Path(contract_record["path"])
    root = contract_path.parents[len(_EXPERIMENT_RELATIVE.parts) - 1]
    if contract_path != root / _EXPERIMENT_RELATIVE:
        raise SavedEvaluationError("ORIGINAL_EXPERIMENT_CONTRACT_PATH_MISMATCH")
    if (binding["official_registry_path"] != old["official_registry_path"]
            or binding["official_registry_path"] != str(root / "contracts/EXPERIMENT_REGISTRY.jsonl")):
        raise SavedEvaluationError("OFFICIAL_REGISTRY_PATH_BINDING_MISMATCH")
    _require_reference(helpers["score_aware_metrics"], root / _SCORE_AWARE_RELATIVE, PINS["score_aware_metrics"],
                       "SCORE_AWARE_HELPER_PATH_BINDING_MISMATCH")
    original_score_aware = old["code_files"]["score_aware_metrics"]
    _require_reference(helpers["score_aware_metrics"], original_score_aware["path"], original_score_aware["sha256"],
                       "ORIGINAL_SCORE_AWARE_BINDING_MISMATCH")
    metrics_path = _declared_frozen_metrics_path(helpers["score_aware_metrics"])
    if helpers["frozen_metrics"]["path"] != str(metrics_path):
        raise SavedEvaluationError("FROZEN_METRICS_PATH_BINDING_MISMATCH")
    for name, filename in (("frozen_settings", "settings.py"), ("frozen_package_init", "__init__.py")):
        if helpers[name]["path"] != str(metrics_path.parent / filename):
            raise SavedEvaluationError(f"FROZEN_METRICS_PACKAGE_PATH_MISMATCH:{name}")
    validate_frozen_evaluator(binding)
    if metadata["append_policy"]["path"] != str(_append_policy_path(official["validator"])):
        raise SavedEvaluationError("OFFICIAL_APPEND_POLICY_PATH_BINDING_MISMATCH")
    policy = json_object(checked_read(metadata["append_policy"]), name="append_policy")
    builder = policy.get("official_builder", {})
    if any(builder.get(key) != official["builder"][key] for key in ("path", "sha256")):
        raise SavedEvaluationError("OFFICIAL_APPEND_POLICY_BUILDER_BINDING_MISMATCH")


def prepare(config: Mapping[str, Any]) -> dict[str, Any]:
    """Bind local metadata once. No approval or real evaluation is generated."""
    root = plain_path(config["project_root"], exists=False)
    recovery = plain_path(config["recovery_root"], exists=False)
    spec = execution_spec(str(config["execution_id"]), config["resources"])
    old_binding_record = file_record(config["candidate_binding_path"], PINS["candidate_binding"])
    old = json_object(checked_read(old_binding_record), name="candidate_binding")
    old_spec_record = file_record(old["run_spec_path"], PINS["candidate_spec"])
    old_spec = json_object(checked_read(old_spec_record), name="candidate_spec")
    if (old.get("route_id") != ROUTE or old.get("execution_id") != CANDIDATE
            or old_spec.get("route_id") != ROUTE or old_spec.get("execution_id") != CANDIDATE
            or old.get("run_spec_sha256") != PINS["candidate_spec"]
            or old.get("input_binding_path") != old_binding_record["path"]):
        raise SavedEvaluationError("ORIGINAL_CANDIDATE_IDENTITY_MISMATCH")
    original_output = plain_path(old["output_root"], exists=False)
    if recovery.is_relative_to(original_output) or original_output.is_relative_to(recovery):
        raise SavedEvaluationError("RECOVERY_ROOT_OVERLAPS_OLD_CANDIDATE")
    contract_record = file_record(root / _EXPERIMENT_RELATIVE, PINS["experiment_contract"])
    contract = json_object(checked_read(contract_record), name="experiment_contract")
    if old_spec.get("decision_gates") != contract["decision_gates"]:
        raise SavedEvaluationError("ORIGINAL_DECISION_GATES_CHANGED")
    _validate_original_evaluation_scope(old["evaluation_contract"])
    seal_record = file_record(original_output / "PREDICTION_SEALED_BEFORE_EVAL_TRUTH_READ.json", PINS["prediction_seal"])
    seal = json_object(checked_read(seal_record), name="prediction_seal")
    validate_seal(seal, EVALUATION, CANDIDATE)
    inputs = {
        "candidate_scores": _opaque_record(original_output / "CANDIDATE_SCORES.csv.gz", PINS["candidate_scores"]),
        "candidate_top3": _opaque_record(original_output / "CANDIDATE_TOP3.csv.gz", PINS["candidate_top3"]),
        "eval_truth": _opaque_record(old["input_files"]["eval_meta.csv.gz"]["path"], old["input_files"]["eval_meta.csv.gz"]["sha256"]),
        "eval_calendar": _opaque_record(old["input_files"]["eval_calendar.csv.gz"]["path"], old["input_files"]["eval_calendar.csv.gz"]["sha256"]),
    }
    for arm in CONTROLS:
        for kind in ("scores", "top3"):
            item = old["baseline_artifacts"][arm]
            name = f"{arm}_{kind}"
            if item[f"{kind}_sha256"] != PINS[name]:
                raise SavedEvaluationError(f"FROZEN_CONTROL_IDENTITY_MISMATCH:{name}")
            inputs[name] = _opaque_record(item[f"{kind}_path"], PINS[name])
    code_files = {name: file_record(Path(__file__).parent / f"{name}.py") for name in SOURCE_NAMES}
    metrics = Path(config["frozen_metrics_path"])
    frozen_helpers, frozen_metadata = bind_frozen_evaluator(metrics)
    native = _old_native_records(old)
    helpers = {
        "accepted_worker": file_record(config["accepted_worker_path"], PINS["accepted_worker"]),
        "score_aware_metrics": file_record(root / _SCORE_AWARE_RELATIVE, PINS["score_aware_metrics"]),
        **frozen_helpers,
        "native_runtime": native["native_runtime"],
        "resource_tree": file_record(old["resource_tree_path"], PINS["resource_tree"]),
    }
    native_reference = native["native_reference_contract"]
    native_doc = json_object(checked_read(native_reference), name="native_reference")
    runtime_record = file_record(native_doc["runtime_contract"]["path"], native_doc["runtime_contract"]["sha256"])
    official = {name: file_record(old["official_helpers"][name]["path"], PINS[name])
                for name in ("execution_guard", "registry_adapter", "builder", "validator")}
    policy_path = _append_policy_path(official["validator"])
    metadata = {"candidate_binding": old_binding_record, "candidate_spec": old_spec_record,
        "prediction_seal": seal_record, "experiment_contract": contract_record,
        "candidate_start": file_record(old["start_receipt_path"], PINS["candidate_start"]),
        "candidate_terminal": file_record(original_output / "CANDIDATE_TERMINAL_RECEIPT.json", PINS["candidate_terminal"]),
        "native_reference": native_reference, "native_runtime_contract": runtime_record,
        "append_policy": file_record(policy_path), **frozen_metadata}
    registry_path = plain_path(root / "contracts/EXPERIMENT_REGISTRY.jsonl")
    registry_bytes = registry_path.read_bytes()
    events = [json_object(line, name="registry_event") for line in registry_bytes.splitlines() if line]
    if not events or any(e.get("execution_id") == spec["execution_id"] for e in events):
        raise SavedEvaluationError("REGISTRY_EMPTY_OR_EXECUTION_ALREADY_PRESENT")
    output = recovery / "execution" / spec["execution_id"]
    trace = recovery / "evidence" / (spec["execution_id"] + ".resource.json")
    spec_path = recovery / "contracts/RUN_SPEC.json"
    binding_path = recovery / "contracts/INPUT_BINDING.json"
    protected = {**inputs, **metadata, **helpers, **official, **code_files,
                 "registry": {"path": str(registry_path)}}
    validate_new_paths(output, trace, original_output, protected, require_new=True)
    for path in (spec_path, binding_path):
        if path.exists() or any(path.resolve() == Path(v["path"]).resolve() for v in protected.values()):
            raise SavedEvaluationError(f"PREPARATION_DESTINATION_EXISTS_OR_PROTECTED:{path}")
    binding = {"schema": "F5_RFF_SAVED_EVALUATION_INPUT_BINDING_V1", "route_id": ROUTE,
        "execution_id": spec["execution_id"], "candidate_execution_id": CANDIDATE,
        "candidate_output_root": str(original_output), "recovery_root": str(recovery),
        "run_spec_path": str(spec_path), "input_binding_path": str(binding_path),
        "parent_release_path": str(recovery / "contracts/PARENT_RELEASE.json"),
        "reviewer_transcript_path": str(recovery / "contracts/INDEPENDENT_LOCAL_REVIEW.json"),
        "output_root": str(output), "resource_trace_path": str(trace),
        "start_receipt_path": str(output / "EVALUATION_START_RECEIPT.json"),
        "resources": spec["resources"], "evaluation_contract": dict(EVALUATION),
        "code_files": code_files, "code_sha256": sha256_bytes(canonical_bytes(code_files)),
        "executable_helpers": helpers, "official_helpers": official,
        "metadata_files": metadata, "input_files": inputs,
        "official_registry_path": str(registry_path),
        "official_registry_sha256_before_start": sha256_bytes(registry_bytes),
        "expected_previous_event_sha256": events[-1]["event_sha256"],
        "expected_route_event_sha256_before_start": [e["event_sha256"] for e in events
            if e.get("route_id") == ROUTE or e.get("experiment_id") == ROUTE],
        "synthetic_only": False, "safety": dict(SAFETY),
        "historical_candidate_mutation": False, "automatic_retry": False}
    _validate_frozen_dependencies(binding)
    # No existing run is touched if either filename was already present.
    binding["run_spec_sha256"] = write_json_exclusive(spec_path, spec)
    binding_sha = write_json_exclusive(binding_path, binding)
    return {"status": "PREPARED_UNSIGNED_REQUIRES_LOCAL_REVIEW_AND_PARENT_RELEASE",
        "run_spec_path": str(spec_path), "run_spec_sha256": binding["run_spec_sha256"],
        "input_binding_path": str(binding_path), "input_binding_sha256": binding_sha,
        "execution_id": spec["execution_id"], "source_code_sha256": binding["code_sha256"],
        "data_rows_read": False, "registry_mutated": False, "execution_started": False}


def validate_seal(seal: Mapping[str, Any], evaluation: Mapping[str, Any], candidate_id: str) -> None:
    expected = {"schema": "F5_FULL64_RFF_PREDICTION_SEAL_V1", "route_id": ROUTE,
        "execution_id": candidate_id, "status": "PREDICTION_FROZEN_BEFORE_EVALUATION_TRUTH_READ",
        "score_kind": "RAW_LOGISTIC_DECISION_MARGIN",
        "probability_kind": "FITTED_LOGISTIC_SIGMOID_NO_CALIBRATOR", "predict_calls": 1,
        "grid_rows": evaluation["grid_rows"], "scoreable_rows": evaluation["scoreable_rows"],
        "evaluation_sessions": evaluation["sessions"], "evaluation_label_values_decoded": False,
        "safety": dict(SAFETY)}
    for key, value in expected.items():
        if canonical_bytes(seal.get(key)) != canonical_bytes(value):
            raise SavedEvaluationError(f"RFF_PREDICTION_SEAL_SCOPE_MISMATCH:{key}")


def load_documents(spec_path: Path, binding_path: Path):
    spec_path, binding_path = plain_path(spec_path), plain_path(binding_path)
    spec_raw, binding_raw = spec_path.read_bytes(), binding_path.read_bytes()
    spec = json_object(spec_raw, name="run_spec")
    binding = json_object(binding_raw, name="input_binding")
    validate_execution_spec(spec)
    expected = {"schema": "F5_RFF_SAVED_EVALUATION_INPUT_BINDING_V1",
        "route_id": ROUTE, "execution_id": spec["execution_id"],
        "candidate_execution_id": CANDIDATE, "run_spec_path": str(spec_path),
        "run_spec_sha256": sha256_bytes(spec_raw), "input_binding_path": str(binding_path),
        "resources": spec["resources"], "evaluation_contract": EVALUATION,
        "synthetic_only": False, "safety": SAFETY, "automatic_retry": False,
        "historical_candidate_mutation": False}
    for key, value in expected.items():
        if canonical_bytes(binding.get(key)) != canonical_bytes(value):
            raise SavedEvaluationError(f"RFF_BINDING_SCOPE_MISMATCH:{key}")
    if set(binding["code_files"]) != set(SOURCE_NAMES) or set(binding["input_files"]) != INPUT_NAMES:
        raise SavedEvaluationError("RFF_EXECUTABLE_OR_INPUT_SET_MISMATCH")
    for category in ("metadata_files", "executable_helpers", "official_helpers", "input_files"):
        for name, record in binding[category].items():
            if name in PINS and record.get("sha256") != PINS[name]:
                raise SavedEvaluationError(f"FROZEN_IDENTITY_PIN_MISMATCH:{name}")
    required = {"metadata_files": {"candidate_binding", "candidate_spec", "prediction_seal",
            "experiment_contract", "candidate_start", "candidate_terminal", "native_reference",
            "native_runtime_contract", "append_policy", "frozen_base_features", "frozen_contract",
            "frozen_evaluator_manifest"},
        "executable_helpers": {"accepted_worker", "score_aware_metrics", "frozen_metrics",
            "frozen_settings", "frozen_package_init", "frozen_common", "frozen_features",
            "native_runtime", "resource_tree"},
        "official_helpers": {"execution_guard", "registry_adapter", "builder", "validator"}}
    for category, names in required.items():
        if set(binding.get(category, {})) != names:
            raise SavedEvaluationError(f"BOUND_DEPENDENCY_CLOSURE_MISMATCH:{category}")
    verify_sources(binding)
    for name in SOURCE_NAMES:
        if Path(binding["code_files"][name]["path"]).resolve() != Path(__file__).parent.resolve() / f"{name}.py":
            raise SavedEvaluationError(f"NEW_SOURCE_IMPORT_ROOT_MISMATCH:{name}")
    _validate_frozen_dependencies(binding)
    recovery = plain_path(binding["recovery_root"], exists=False)
    output = recovery / "execution" / spec["execution_id"]
    expected_paths = {"recovery_root": recovery, "output_root": output,
        "run_spec_path": recovery / "contracts/RUN_SPEC.json",
        "input_binding_path": recovery / "contracts/INPUT_BINDING.json",
        "parent_release_path": recovery / "contracts/PARENT_RELEASE.json",
        "reviewer_transcript_path": recovery / "contracts/INDEPENDENT_LOCAL_REVIEW.json",
        "resource_trace_path": recovery / "evidence" / (spec["execution_id"] + ".resource.json"),
        "start_receipt_path": output / "EVALUATION_START_RECEIPT.json"}
    if any(binding.get(name) != str(path) for name, path in expected_paths.items()):
        raise SavedEvaluationError("EVALUATION_EXECUTION_PATH_IDENTITY_MISMATCH")
    candidate = plain_path(binding["candidate_output_root"], exists=False)
    if recovery.is_relative_to(candidate) or candidate.is_relative_to(recovery):
        raise SavedEvaluationError("RECOVERY_ROOT_OVERLAPS_OLD_CANDIDATE")
    protected = {f"{category}:{name}": record for category in
        ("input_files", "metadata_files", "executable_helpers", "official_helpers", "code_files")
        for name, record in binding[category].items()}
    for name in ("official_registry_path", "run_spec_path", "input_binding_path",
                 "parent_release_path", "reviewer_transcript_path"):
        protected[name] = {"path": binding[name]}
    # load_documents is also used after RUN_STARTED; freshness is the owner's
    # pre-claim responsibility, while aliases remain forbidden on every read.
    validate_new_paths(output, expected_paths["resource_trace_path"], candidate, protected, require_new=False)
    return spec, binding, spec_raw, binding_raw


def verify_review_release(binding: Mapping[str, Any], spec_raw: bytes, binding_raw: bytes) -> dict[str, Any]:
    release_record = file_record(binding["parent_release_path"])
    review_record = file_record(binding["reviewer_transcript_path"])
    release = json_object(checked_read(release_record), name="parent_release")
    review = json_object(checked_read(review_record), name="local_review")
    identities = {"route_id": binding["route_id"], "execution_id": binding["execution_id"],
        "candidate_execution_id": binding["candidate_execution_id"],
        "run_spec_sha256": sha256_bytes(spec_raw), "input_binding_sha256": sha256_bytes(binding_raw),
        "source_code_sha256": binding["code_sha256"]}
    reviewer = review.get("reviewer_agent")
    if (not isinstance(reviewer, str) or not reviewer.strip()
            or not isinstance(review.get("writer_agent"), str) or not review["writer_agent"].strip()
            or reviewer == review["writer_agent"]):
        raise SavedEvaluationError("INDEPENDENT_LOCAL_REVIEWER_REQUIRED")
    review_expected = {**identities, "schema": "F5_RFF_SAVED_EVAL_LOCAL_REVIEW_V1",
        "reviewer_verdict": "PASS", "REVIEWED": "PASS", "BEHAVIOR_VERIFIED": "PASS",
        "scope": "EXACT_LOCAL_RFF_SAVED_EVALUATION_BINDING"}
    for key, value in review_expected.items():
        if canonical_bytes(review.get(key)) != canonical_bytes(value):
            raise SavedEvaluationError(f"REVIEW_IDENTITY_OR_SCOPE_MISMATCH:{key}")
    release_expected = {**identities, "schema": "F5_RFF_SAVED_EVAL_PARENT_RELEASE_V1",
        "active": True, "saved_prediction_evaluation_authorized": True,
        "automatic_retry": False, "evaluation_truth_decode_authorized": 1,
        "candidate_model_load_authorized": False,
        **{key: 0 for key in ZERO_AUTHORIZATIONS}, "reviewer_agent": reviewer,
        "reviewer_transcript_path": review_record["path"],
        "reviewer_transcript_sha256": review_record["sha256"],
        "resource_caps": binding["resources"], "safety": SAFETY,
        "official_registry_path": binding["official_registry_path"],
        "official_registry_sha256_before_start": binding["official_registry_sha256_before_start"],
        "expected_route_event_sha256_before_start": binding["expected_route_event_sha256_before_start"]}
    for key, value in release_expected.items():
        if canonical_bytes(release.get(key)) != canonical_bytes(value):
            raise SavedEvaluationError(f"PARENT_RELEASE_SCOPE_MISMATCH:{key}")
    if (not isinstance(release.get("parent_authorization_id"), str) or not release["parent_authorization_id"].strip()
            or not isinstance(release.get("parent_controller_id"), str) or not release["parent_controller_id"].strip()
            or release["parent_controller_id"] == reviewer):
        raise SavedEvaluationError("PARENT_AUTHORIZATION_IDENTITY_REQUIRED")
    return {"release": release_record, "review": review_record}
