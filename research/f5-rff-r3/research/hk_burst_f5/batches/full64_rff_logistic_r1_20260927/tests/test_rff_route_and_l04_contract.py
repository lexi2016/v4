from __future__ import annotations

import hashlib
import json
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

import rff_candidate_entry as route_entry
import rff_evaluation_completion as completion
from rff_evaluation_completion import (
    EvaluationCompletionError,
    classify_failure,
    read_completion_receipt,
    write_completion_receipt,
)

_PINNED_CONTRACT_PATH = route_entry.FROZEN_CONTRACT_PATH
_PINNED_CONTRACT_SHA256 = route_entry.FROZEN_CONTRACT_SHA256


def _canonical_sha(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _synthetic_event_spec(*, contract_path, artifact_path, route_id, execution_id,
                          event_id, stage, event_type, decision, truth_access,
                          sealed_status, contract_sha, input_binding_sha,
                          deterministic_metrics):
    return {
        "schema_version": "1.0",
        "registry_event_id": event_id,
        "registration_mode": "LIVE_EXECUTION",
        "route_id": route_id,
        "experiment_id": route_id,
        "execution_id": execution_id,
        "track_id": "HK_BURST_F5_FULL_HISTORY_RESEARCH",
        "stage": stage,
        "event_type": event_type,
        "occurred_at": "2000-01-01T00:00:00Z",
        "occurred_at_reason": "SYNTHETIC_TEST_EVENT_TIME",
        "contract_path": str(contract_path),
        "artifact_paths": [str(artifact_path)],
        "input_identity": {},
        "input_sha256": "d" * 64,
        "code_sha256": "e" * 64,
        "config_sha256": "f" * 64,
        "baseline_id": "F5_FULL64_ORIGINAL_PLUS_PATH_BINARY_2024",
        "one_variable": "SYNTHETIC_REGISTRY_CHAIN_ONLY",
        "signal_date_range": "SYNTHETIC",
        "target_date_range": "SYNTHETIC",
        "truth_access": truth_access,
        "sealed_status": sealed_status,
        "runtime": {"python": "synthetic"},
        "device": "CPU_SYNTHETIC",
        "checkpoint_ref": None,
        "deterministic_metrics": deterministic_metrics,
        "decision": decision,
        "stop_reason": "SYNTHETIC_TEST_EVENT",
        "evidence_level": "ENGINEERING_CANARY_ONLY",
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "contract_sha256": contract_sha,
        "input_binding_sha256": input_binding_sha,
    }


def _install_synthetic_validator_policy(binding, prefix_raw, prefix_events):
    validator = completion._load_bound_validator(binding)
    debt_records = validator._debt_records(prefix_events)
    required = [r["index_1"] for r in debt_records if r["kind"] == "REQUIRED_FIELDS_MISSING"]
    null_reasons = [r["index_1"] for r in debt_records if r["kind"] == "NULL_REASON_MISSING"]
    missing_ids = [i + 1 for i, event in enumerate(prefix_events)
                   if "registry_event_id" not in event or event.get("registry_event_id") is None]
    nonempty_ids = [event.get("registry_event_id") for event in prefix_events if event.get("registry_event_id")]
    synthetic_policy = {
        "policy_id": "RFF_SYNTHETIC_FIXTURE_ONLY",
        "registry_path": str(Path(binding["official_registry_path"]).resolve()),
        "legacy_prefix": {
            "event_count": len(prefix_events),
            "size_bytes": len(prefix_raw),
            "sha256": hashlib.sha256(prefix_raw).hexdigest(),
            "head_event_sha256": prefix_events[-1]["event_sha256"],
        },
        "legacy_schema_debt": {
            "events_with_debt": len(debt_records),
            "required_fields_missing": len(required),
            "null_reason_missing": len(null_reasons),
            "missing_or_null_registry_event_id": len(missing_ids),
            "nonempty_registry_event_id": len(nonempty_ids),
            "index_base": "one_based_inclusive_ranges",
            "required_fields_missing_ranges": validator._ranges_one_based(required),
            "null_reason_missing_ranges": validator._ranges_one_based(null_reasons),
            "records_sha256": validator._debt_records_sha256(prefix_events),
        },
        "grandfathered_current_snapshot": {
            "purpose": "Synthetic RFF fixture anchor only.",
            "line_range_1_based": [645, len(prefix_events)],
            "strict_suffix_start_line_1_based": len(prefix_events) + 1,
            "anchor": {
                "event_count": len(prefix_events),
                "size_bytes": len(prefix_raw),
                "sha256": hashlib.sha256(prefix_raw).hexdigest(),
                "head_event_sha256": prefix_events[-1]["event_sha256"],
            },
            "preexisting_schema_status": "FULL_LEGACY_SCHEMA_VALIDATION=CANNOT_CONFIRM_SYNTHETIC_FIXTURE_ONLY",
        },
        "deferred_suffix_debt": None,
        "additional_deferred_suffix_debts": [],
    }
    validator.POLICY = copy.deepcopy(synthetic_policy)
    return validator


def _write_synthetic_contract(tmp_path: Path):
    contract = {
        "schema": "F5_FULL64_RFF_LOGISTIC_CONTRACT_V1",
        "status": "FROZEN_BEFORE_SOURCE_IMPLEMENTATION",
        "route_id": "F5_FULL64_RFF_LOGISTIC_R1_20260927",
        "baseline_id": "F5_FULL64_ORIGINAL_PLUS_PATH_BINARY_2024",
        "one_variable": "Replace the original XENDCG learner with train-only mean imputation/standardization, fixed RFF-RBF(256,gamma=1/64,seed=42), and equal-weight L2 logistic regression C=1.",
        "input_identity": {
            "controls": ["FROZEN_UNWEIGHTED_PLUS_PATH", "FROZEN_BASE34"],
            "evaluation_fold": "full exposed 2024 grid, original Top3 helper, 246 sessions and 738 slots",
            "parent_training_plan_path": str(route_entry.FROZEN_SOURCE_PARENT_PLAN_PATH),
            "parent_training_plan_sha256": route_entry.FROZEN_SOURCE_PARENT_PLAN_SHA256,
        },
        "preprocessing": {
            "feature_order_or_row_filter_change": False,
            "fit_rows": "training fold only",
            "infinity": "reject before fit or prediction",
            "missing_value_rule": "per-feature train mean; all-NaN train feature mean is 0; then standardize",
            "standardization": "train-only population mean/std; zero or non-finite std becomes 1; evaluation uses frozen train statistics",
        },
        "random_fourier_features": {
            "chunking": "fixed 4096-row transform chunks; one preallocated training RFF matrix; evaluation projected in chunks after the training matrix is released",
            "dimension": 256,
            "draw_order": "normal projection W [64,256] with scale sqrt(2*gamma), then uniform phase b [256] in [0,2*pi)",
            "dtype": "float64",
            "gamma": 0.015625,
            "kernel": "RBF",
            "map": "sqrt(2/256) * cos(X_standardized @ W + b)",
            "rng": "numpy.random.RandomState(42)",
            "seed": 42,
        },
        "learner": {
            "C": 1.0,
            "failed_fit_consumes_budget": True,
            "family": "binary logistic regression",
            "fit_budget": 1,
            "max_call_counts": {"calibrator_fit": 0, "candidate_fit": 1, "candidate_full_S_predict": 1,
                                "control_fit": 0, "control_predict": 0, "evaluation_truth_decode": 1},
            "nonconvergence": "STOP_OPTIMIZER_NOT_CONVERGED; record full OptimizeResult; no changed options, retry, or evaluation",
            "objective": "mean(binary cross-entropy) + ||w||^2/(2*C*n); intercept is unpenalized",
            "optimizer": "SciPy L-BFGS-B with analytic gradient",
            "options": {"ftol": 2.220446049250313e-09, "gtol": 1e-05, "maxcor": 10, "maxfun": 5000,
                        "maxiter": 200, "maxls": 20},
            "record_full_optimizer_result": True,
            "sample_weights": "all ones; no class, episode, day, or control weights",
        },
        "prediction_and_evaluation": {
            "decision_scope": "exposed-2024-development only; max DIRECTION_ONLY",
            "evaluator": "original accepted score-aware and episode metric helpers; original PLUS and BASE34 controls unchanged",
            "event_probability": "sigmoid(raw margin) emitted by the fitted logistic classifier; no separate calibrator",
            "prediction": "one public full-S call; internal fixed transform chunks do not create extra model-predict calls",
            "ranking_score": "raw logistic decision margin; original raw-ranking-score AP/Top3 path",
            "save_predictions_before_truth": True,
            "selection_slots_denominator": 738,
            "truth_positive_denominator": 126,
        },
        "decision_gates": {
            "development_primary": {"metric": "paired lower candidate-minus-frozen-PLUS", "operator": ">", "value": 0.0},
            "never_infer_breakthrough_from_primary_alone": True,
            "original_promotion_gates_unchanged": {
                "ap_known_gain_min": 0.0, "brier_known_gain_max": 0.0, "empty_slots_max": 0,
                "episode_coverage_gain_min": 0.0, "paired_precision_lower_gain": 0.03,
                "positive_years_min": 2, "promotion_now": False, "random_lift_lower": 2.0,
                "relative_precision_lower_ratio": 1.25, "selected_unknown_fraction_max": 0.05,
                "single_exposed_year_blocks_promotion": True,
            },
            "practical_base34": {"metric": "paired lower candidate-minus-frozen-BASE34", "operator": ">=", "value": 0.03},
        },
        "resources": {"aggregate_process_tree_rss_bytes_max": 3221225472, "cpu_threads": 4,
                      "monitor": "existing sampled resource monitor; sampling is not a hard peak guarantee",
                      "wall_seconds_max": 1800},
        "safety": {"buy_gate_updated": False, "orders_sent": False, "production_allowed": False, "research_only": True},
    }
    path = tmp_path / "EXPERIMENT_CONTRACT.synthetic.json"
    _write_json(path, contract)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    route_entry.FROZEN_CONTRACT_PATH = path
    route_entry.FROZEN_CONTRACT_SHA256 = digest
    completion.FROZEN_CONTRACT_PATH = path
    completion.FROZEN_CONTRACT_SHA256 = digest
    return path, digest, contract


def _completion_case(tmp_path: Path):
    route = "F5_FULL64_RFF_LOGISTIC_R1_20260927"
    execution = route + "_CANDIDATE_01"
    root = tmp_path / "execution"
    root.mkdir()
    registry = tmp_path / "EXPERIMENT_REGISTRY.jsonl"
    source = tmp_path / "bound_source.py"
    source.write_text("# synthetic bound source\n", encoding="utf-8")
    source_map = {"worker": {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}}
    code_sha = _canonical_sha(source_map)
    frozen_input = tmp_path / "frozen-input.bin"
    frozen_input.write_bytes(b"synthetic frozen input")
    frozen_input_sha = hashlib.sha256(frozen_input.read_bytes()).hexdigest()
    spec_path = tmp_path / "CANDIDATE_RUN_SPEC.json"
    binding_path = tmp_path / "CANDIDATE_INPUT_BINDING.json"
    contract_path, contract_sha, contract = _write_synthetic_contract(tmp_path)
    evaluation_definition = {
        "scope": contract["prediction_and_evaluation"]["decision_scope"],
        "evaluator": contract["prediction_and_evaluation"]["evaluator"],
        "ranking_score": contract["prediction_and_evaluation"]["ranking_score"],
        "event_probability": contract["prediction_and_evaluation"]["event_probability"],
        "selection_slots_denominator": contract["prediction_and_evaluation"]["selection_slots_denominator"],
        "truth_positive_denominator": contract["prediction_and_evaluation"]["truth_positive_denominator"],
        "evaluation_fold": contract["input_identity"]["evaluation_fold"],
        "controls": contract["input_identity"]["controls"],
        "decision_gates": contract["decision_gates"],
    }
    model_definition = {
        "preprocessing": contract["preprocessing"],
        "random_fourier_features": contract["random_fourier_features"],
        "learner": contract["learner"],
    }
    rff_definition = dict(contract["random_fourier_features"])
    rff_definition.pop("chunking")
    rff_definition["chunk_rows"] = 4096
    spec = {
        "schema": "F5_FULL64_RFF_LOGISTIC_RUN_SPEC_V1",
        "route_id": route,
        "execution_id": execution,
        "baseline_id": contract["baseline_id"],
        "one_variable": contract["one_variable"],
        "experiment_contract_sha256": contract_sha,
        "preprocessing": contract["preprocessing"],
        "random_fourier_features": rff_definition,
        "decision_gates": contract["decision_gates"],
        "evaluation_definition": evaluation_definition,
    }
    spec["model_definition_sha256"] = _canonical_sha(model_definition)
    spec["evaluation_definition_sha256"] = _canonical_sha(spec["evaluation_definition"])
    _write_json(spec_path, spec)
    binding = {
        "route_id": route,
        "execution_id": execution,
        "run_spec_path": str(spec_path.resolve()),
        "run_spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
        "input_binding_path": str(binding_path.resolve()),
        "output_root": str(root.resolve()),
        "official_registry_path": str(registry.resolve()),
        "code_sha256": code_sha,
        "code_files": source_map,
        "input_files": {"fixture.bin": {"path": str(frozen_input.resolve()), "sha256": frozen_input_sha}},
        "resources": {
            "cpu_threads": 4,
            "aggregate_process_tree_rss_bytes_max": 3221225472,
            "wall_seconds_max": 1800,
        },
        "experiment_contract_path": str(contract_path.resolve()),
        "experiment_contract_sha256": contract_sha,
        "official_helpers": {
            "validator": {
                "path": "/Users/lexi/Desktop/学习/因子工厂/contracts/validate_experiment_registry_append_compatibility_v1.py",
                "sha256": "80e49d05d13f33ee7e2cb8d4d10cae0e297bcdf5b113ff857d3bd141dea0f438",
            },
            "builder": {
                "path": "/Users/lexi/Desktop/学习/因子工厂/contracts/build_experiment_registry_backfill_20260821.py",
                "sha256": "df4bfc89fa5487966a8c7e1c1c50832e140339c2ccda3a02a9a59e5aaaeb58cf",
            },
            "registry_adapter": {
                "path": "/Users/lexi/Desktop/学习/因子工厂/workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity/registry_adapter.py",
                "sha256": "8596f2a20c165b5fbc2b92a597cb3e1177f6e40bfefac62753b40b3c7daae17f",
            },
            "execution_guard": {
                "path": "/Users/lexi/Desktop/学习/因子工厂/workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity/execution_guard_core.py",
                "sha256": "85929366a7b018480085c02f80edd312f7f47de94bab5c32982d4e8637d7d7e0",
            },
        },
    }
    _write_json(binding_path, binding)

    names = {
        "start_receipt": "CANDIDATE_START_RECEIPT.json",
        "run_receipt": "CANDIDATE_RUN_RECEIPT.json",
        "resource_trace": "CANDIDATE_RESOURCE_TRACE.json",
        "fit_receipt": "CANDIDATE_FIT_RECEIPT.json",
        "optimizer_result": "OPTIMIZER_RESULT.json",
        "prediction_seal": "PREDICTION_SEALED_BEFORE_EVAL_TRUTH_READ.json",
        "truth_read_start": "EVALUATION_TRUTH_READ_START.json",
        "metrics": "METRICS.json",
        "result_receipt": "CANDIDATE_RESULT_RECEIPT.json",
        "worker_status": "CANDIDATE_WORKER_STATUS.json",
        "model": "CANDIDATE_MODEL.txt",
        "scores": "CANDIDATE_SCORES.csv.gz",
        "raw_scores": "CANDIDATE_RAW_SCORES.npy",
        "top3": "CANDIDATE_TOP3.csv.gz",
        "terminal_receipt": "CANDIDATE_TERMINAL_RECEIPT.json",
        "input_hash_receipt": "CANDIDATE_INPUT_HASH_RECEIPT.json",
    }
    paths = {key: root / name for key, name in names.items()}
    binding.update({key + "_path": str(paths[key].resolve()) for key in ("start_receipt", "run_receipt", "resource_trace")})
    _write_json(binding_path, binding)

    start_sha = _write_json(paths["start_receipt"], {
        "route_id": route, "execution_id": execution, "status": "RUN_STARTED_DURABLE",
        "run_spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
        "input_binding_sha256": hashlib.sha256(binding_path.read_bytes()).hexdigest(),
        "start_event_sha256": None,
    })
    resource_sha = _write_json(paths["resource_trace"], {
        "schema": "F5_META2023_RESOURCE_TRACE_V1",
        "rss_backend": "synthetic",
        "monitor_scope": "caller_plus_worker_and_all_worker_descendants",
        "monitor_start": "before_spawn_and_before_first_model_input_read",
        "monitor_stop": "after_worker_exit_or_breach_and_post_trace_fsync_cap_check",
        "wall_seconds_max": 1800.0,
        "aggregate_rss_bytes_max": 3221225472,
        "threads": 4,
        "sample_interval_seconds": 0.05,
        "rss_measurement": "sampled_process_tree_observation_not_absolute_peak",
        "rss_cap_enforcement": "terminate_on_observed_aggregate_tree_rss_exceedance",
        "hard_peak_memory_guarantee": False,
        "elapsed_seconds": 12.0,
        "peak_aggregate_tree_rss_bytes": 1024,
        "worker_exitcode": 0,
        "terminal_reason": None,
        "worker_termination": None,
        "samples": [],
    })
    model_sha = _write_json(paths["model"], {"route_id": route, "execution_id": execution, "synthetic_only": True})
    paths["scores"].write_bytes(b"synthetic scores\n")
    paths["raw_scores"].write_bytes(b"synthetic raw scores\n")
    paths["top3"].write_bytes(b"synthetic top3\n")
    artifact_sha = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items() if path.is_file()}

    _write_json(paths["input_hash_receipt"], {
        "route_id": route, "execution_id": execution, "evaluation_label_values_decoded": False,
        "input_sha256": {"fixture.bin": frozen_input_sha},
    })
    _write_json(paths["optimizer_result"], {"route_id": route, "execution_id": execution, "success": True, "status": 0, "nit": 4})
    _write_json(paths["fit_receipt"], {
        "route_id": route, "execution_id": execution, "status": "FIT_COMPLETED",
        "fit_calls": 1, "fit_call_entered": True, "real_fit_returned_count": 1,
        "model_sha256": model_sha,
        "optimizer_result_sha256": hashlib.sha256(paths["optimizer_result"].read_bytes()).hexdigest(),
    })
    fit_sha = hashlib.sha256(paths["fit_receipt"].read_bytes()).hexdigest()
    seal_sha = _write_json(paths["prediction_seal"], {
        "route_id": route, "execution_id": execution,
        "status": "PREDICTION_FROZEN_BEFORE_EVALUATION_TRUTH_READ",
        "evaluation_label_values_decoded": False,
        "predict_calls": 1, "scoreable_rows": 120084, "grid_rows": 169986, "evaluation_sessions": 246,
        "candidate_scores_sha256": hashlib.sha256(paths["scores"].read_bytes()).hexdigest(),
        "candidate_raw_scores_sha256": hashlib.sha256(paths["raw_scores"].read_bytes()).hexdigest(),
        "candidate_top3_sha256": hashlib.sha256(paths["top3"].read_bytes()).hexdigest(),
    })
    _write_json(paths["truth_read_start"], {
        "route_id": route, "execution_id": execution,
        "first_eval_truth_decode_after_prediction_seal": True,
        "prediction_seal_sha256": seal_sha,
        "candidate_scores_sha256": hashlib.sha256(paths["scores"].read_bytes()).hexdigest(),
        "candidate_raw_scores_sha256": hashlib.sha256(paths["raw_scores"].read_bytes()).hexdigest(),
        "candidate_top3_sha256": hashlib.sha256(paths["top3"].read_bytes()).hexdigest(),
    })
    _write_json(paths["metrics"], {
        "route_id": route, "execution_id": execution,
        "status": "EXPOSED_RETROSPECTIVE_DEVELOPMENT_EVALUATION",
        "selection_slots": 738, "truth_positive_denominator": 126,
        "development_gates": {"development_decision": "DIRECTION_ONLY"},
        "grid_rows": 169986, "scoreable_rows": 120084, "sessions": 246,
        "fit_calls": 1, "fit_call_entered": True, "real_fit_returned_count": 1,
        "predict_calls": 1, "control_fit_calls": 0, "control_predict_calls": 0,
        "calibrator_fit_calls": 0, "evaluation_truth_decodes": 1,
        "evaluation_label_values_decoded": True,
        "fit_receipt_sha256": fit_sha, "prediction_seal_sha256": seal_sha,
        "optimizer_result_sha256": hashlib.sha256(paths["optimizer_result"].read_bytes()).hexdigest(),
    })
    metrics_sha = hashlib.sha256(paths["metrics"].read_bytes()).hexdigest()
    scores_sha = hashlib.sha256(paths["scores"].read_bytes()).hexdigest()
    raw_sha = hashlib.sha256(paths["raw_scores"].read_bytes()).hexdigest()
    top3_sha = hashlib.sha256(paths["top3"].read_bytes()).hexdigest()
    result_sha = _write_json(paths["result_receipt"], {
        "route_id": route, "execution_id": execution, "status": "CANDIDATE_FIT_PREDICT_AND_FULL2024_EVALUATION_COMPLETED",
        "run_spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
        "input_binding_sha256": hashlib.sha256(binding_path.read_bytes()).hexdigest(),
        "source_code_sha256": code_sha,
        "input_sha256": {"fixture.bin": frozen_input_sha},
        "evaluation_truth_decodes": 1,
        "fit_receipt_sha256": fit_sha, "prediction_seal_sha256": seal_sha,
        "optimizer_result_sha256": hashlib.sha256(paths["optimizer_result"].read_bytes()).hexdigest(),
        "fit_calls": 1, "fit_call_entered": True, "real_fit_returned_count": 1, "predict_calls": 1,
        "control_fit_calls": 0, "control_predict_calls": 0, "calibrator_fit_calls": 0,
        "evaluation_label_values_decoded": True,
        "metrics_sha256": metrics_sha, "candidate_model_sha256": model_sha,
        "candidate_scores_sha256": scores_sha, "candidate_raw_scores_sha256": raw_sha,
        "candidate_top3_sha256": top3_sha,
    })
    _write_json(paths["worker_status"], {
        "route_id": route, "execution_id": execution,
        "status": "CANDIDATE_FIT_PREDICT_AND_FULL2024_EVALUATION_COMPLETED",
        "fit_calls": 1, "fit_call_entered": True, "real_fit_returned_count": 1,
        "predict_calls": 1, "control_fit_calls": 0, "control_predict_calls": 0,
        "calibrator_fit_calls": 0, "evaluation_truth_decodes": 1,
        "evaluation_label_values_decoded": True,
    })
    run_sha = _write_json(paths["run_receipt"], {
        "route_id": route, "execution_id": execution, "terminal_status": "COMPLETED",
        "evaluation_label_values_decoded": True,
        "run_spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
        "input_binding_sha256": hashlib.sha256(binding_path.read_bytes()).hexdigest(),
        "resource_trace_sha256": resource_sha,
        "resource_monitor": {
            "elapsed_seconds": 12.0,
            "peak_aggregate_tree_rss_bytes": 1024,
            "worker_exitcode": 0,
            "terminal_reason": None,
            "wall_seconds_max": 1800.0,
            "aggregate_rss_bytes_max": 3221225472,
            "threads": 4,
            "hard_peak_memory_guarantee": False,
            "post_trace_fsync_terminal_check": {
                "elapsed_seconds": 12.0, "aggregate_tree_rss_bytes": 1024,
                "process_ids": [], "after_trace_fsync": True,
            },
            "final_post_fsync_check": {
                "elapsed_seconds": 12.0, "aggregate_tree_rss_bytes": 1024,
                "process_ids": [], "after_final_trace_fsync": True,
            },
        },
    })
    validator = completion._load_bound_validator(binding)
    builder = validator.OFFICIAL
    prefix_specs = [
        _synthetic_event_spec(
            contract_path=spec_path, artifact_path=frozen_input,
            route_id="RFF_SYNTHETIC_LEGACY_PREFIX",
            execution_id=f"RFF_SYNTHETIC_PREFIX_EXEC_{index:04d}",
            event_id=f"RFF_SYNTHETIC_PREFIX_EVENT_{index:04d}",
            stage="SYNTHETIC_PREFIX", event_type="RUN_STARTED", decision="RUNNING",
            truth_access="NOT_OPENED", sealed_status="ENGINEERING_ONLY",
            contract_sha=hashlib.sha256(spec_path.read_bytes()).hexdigest(),
            input_binding_sha=hashlib.sha256(binding_path.read_bytes()).hexdigest(),
            deterministic_metrics={"planned_real_fit_count": 0, "real_fit_budget_debit": 0},
        )
        for index in range(1, 646)
    ]
    prefix_events = builder.materialize(prefix_specs)
    prefix_raw = builder._registry_payload(prefix_events)
    validator = _install_synthetic_validator_policy(binding, prefix_raw, prefix_events)
    prefix_check = validator.validate_registry_bytes(prefix_raw, source="rff-synthetic-prefix-preflight")
    assert prefix_check["APPEND_COMPATIBILITY"] == "PASS" and prefix_check["events"] == 645

    contract_sha = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    input_binding_sha = hashlib.sha256(binding_path.read_bytes()).hexdigest()
    start_spec = _synthetic_event_spec(
        contract_path=spec_path, artifact_path=frozen_input, route_id=route,
        execution_id=execution, event_id=f"{execution}_RUN_STARTED", stage="RFF_RUN_STARTED",
        event_type="RUN_STARTED", decision="RUNNING",
        truth_access="TRAIN_LABELS_READ_EVAL_LABELS_NOT_DECODED",
        sealed_status="EXPOSED_2024_LABELS_NOT_DECODED", contract_sha=contract_sha,
        input_binding_sha=input_binding_sha,
        deterministic_metrics={"planned_real_fit_count": 1, "real_fit_budget_debit": 1},
    )
    terminal_spec = _synthetic_event_spec(
        contract_path=spec_path, artifact_path=frozen_input, route_id=route,
        execution_id=execution, event_id=f"{execution}_TERMINAL", stage="RFF_TERMINAL",
        event_type="TERMINAL", decision="COMPLETED",
        truth_access="EVAL_LABELS_DECODED_AFTER_PREDICTION_SEAL",
        sealed_status="EXPOSED_2024_POST_SEAL_EVALUATION", contract_sha=contract_sha,
        input_binding_sha=input_binding_sha,
        deterministic_metrics={
            "planned_real_fit_count": 1, "real_fit_budget_debit": 1,
            "fit_call_entered": True, "real_fit_returned_count": 1, "predict_calls": 1,
            "control_fit_calls": 0, "control_predict_calls": 0, "calibrator_fit_calls": 0,
        },
    )
    suffix_events = builder.materialize(
        [start_spec, terminal_spec], starting_previous_sha=prefix_events[-1]["event_sha256"],
    )
    start_event, terminal_event = suffix_events
    start_event_sha = start_event["event_sha256"]
    terminal_event_sha = terminal_event["event_sha256"]
    start_receipt_doc = json.loads(paths["start_receipt"].read_text(encoding="utf-8"))
    start_receipt_doc["start_event_sha256"] = start_event_sha
    start_sha = _write_json(paths["start_receipt"], start_receipt_doc)
    registry.write_bytes(prefix_raw + builder._registry_payload(suffix_events))
    registry_sha = hashlib.sha256(registry.read_bytes()).hexdigest()
    terminal_sha = _write_json(paths["terminal_receipt"], {
        "route_id": route, "execution_id": execution, "terminal_status": "COMPLETED",
        "terminal_event_sha256": terminal_event_sha, "previous_event_sha256": start_event_sha,
        "official_registry_sha256_after_terminal": registry_sha,
        "start_receipt_sha256": start_sha, "run_receipt_sha256": run_sha,
    })
    summary = {
        "execution_id": execution, "terminal_status": "COMPLETED",
        "real_fit_budget_debit": 1, "fit_call_entered": True, "real_fit_returned_count": 1,
        "predict_calls": 1, "candidate_terminal_receipt_sha256": terminal_sha,
        "terminal_event_sha256": terminal_event_sha,
        "official_registry_sha256_after_terminal": registry_sha,
    }
    return spec_path, binding_path, paths, summary, {
        "execution_id": execution, "start_event_sha256": start_event_sha,
        "terminal_event_sha256": terminal_event_sha,
    }


def test_actual_route_guard_arm_and_profile_are_bound_without_claim_side_effects():
    class FakeAdapter:
        def __init__(self, *, event_profile, **kwargs):
            self.event_profile = event_profile

    class FakeGuard:
        def __init__(self, adapter, experiment_id, max_real_fit_debits):
            self.experiment_id = experiment_id

        def claim(self, *, execution_id, arm, contract_sha256, input_binding_sha256):
            return SimpleNamespace(
                execution_id=execution_id, arm=arm,
                contract_sha256=contract_sha256,
                input_binding_sha256=input_binding_sha256,
            )

    fake_entry = SimpleNamespace(
        _make_candidate_adapter=lambda *args, **kwargs: FakeAdapter,
        _load_official_modules=lambda binding: (object(), SimpleNamespace(ExecutionGuard=FakeGuard)),
    )
    spec = {
        "route_id": "RFF_ROUTE", "one_variable": "FIXED_RFF_LOGISTIC",
        "baseline_id": "F5_FULL64_ORIGINAL_PLUS_PATH_BINARY_2024",
    }
    binding = {
        "route_id": "RFF_ROUTE", "execution_id": "RFF_EXEC", "code_sha256": "code",
        "run_spec_path": "/tmp/run-spec.json", "input_binding_path": "/tmp/input-binding.json",
    }
    route_entry._adapt_owner(fake_entry, spec, binding)
    adapter_class = fake_entry._make_candidate_adapter(
        None, None, spec, binding, run_spec_path=Path("run"), input_binding_path=Path("binding"),
        release_path=Path("release"), reviewer_transcript_path=Path("review"), registry_path=Path("registry"),
        expected_registry_sha="registry-sha", release_sha="release-sha", review_sha="review-sha",
        start_registry_snapshot={},
    )
    adapter = adapter_class(event_profile={"one_variable": "legacy"})
    assert adapter.event_profile["one_variable"] == "FIXED_RFF_LOGISTIC"
    assert adapter.event_profile["route_id"] == "RFF_ROUTE"
    _, guard_module = fake_entry._load_official_modules(binding)
    claim = guard_module.ExecutionGuard(adapter, "RFF_ROUTE", 1).claim(
        execution_id="RFF_EXEC", arm=route_entry.EXPECTED_LEGACY_ARM,
        contract_sha256="contract", input_binding_sha256="binding",
    )
    assert claim.arm == route_entry.ROUTE_ARM
    assert claim.execution_id == "RFF_EXEC"
    assert claim.contract_sha256 == "contract"
    assert claim.input_binding_sha256 == "binding"


def test_l04_completion_receipt_binds_successful_full_chain_and_readback(tmp_path):
    spec_path, binding_path, paths, summary, _ = _completion_case(tmp_path)
    receipt = write_completion_receipt(spec_path=spec_path, binding_path=binding_path, run_summary=summary)
    assert receipt["status"] == "EVALUATION_COMPLETED"
    assert receipt["budget"] == {
        "candidate_fit_calls": 1,
        "candidate_fit_call_entered": True,
        "candidate_fit_returned_count": 1,
        "candidate_predict_calls": 1,
        "control_fit_calls": 0,
        "control_predict_calls": 0,
        "calibrator_fit_calls": 0,
        "evaluation_truth_decodes": 1,
    }
    reread = read_completion_receipt(
        paths["metrics"].parent / "EVALUATION_COMPLETION_RECEIPT.json",
        spec_path=spec_path,
        binding_path=binding_path,
    )
    assert reread["official_terminal"]["terminal_event_sha256"] == summary["terminal_event_sha256"]


@pytest.mark.parametrize("mutation,expected", [
    ("missing_metrics", "L04_ARTIFACT_MISSING_OR_SYMLINK:metrics"),
    ("cross_execution", "L04_CROSS_EXECUTION_ARTIFACT:fit"),
    ("terminal_pending", "L04_OFFICIAL_REGISTRY_VALIDATION_FAILED"),
])
def test_l04_rejects_incomplete_or_cross_execution_terminal(tmp_path, mutation, expected):
    spec_path, binding_path, paths, summary, _ = _completion_case(tmp_path)
    if mutation == "missing_metrics":
        paths["metrics"].unlink()
    elif mutation == "cross_execution":
        _write_json(paths["fit_receipt"], {
            "route_id": "F5_FULL64_RFF_LOGISTIC_R1_20260927",
            "execution_id": "OTHER_EXECUTION", "status": "FIT_COMPLETED",
            "fit_calls": 1, "fit_call_entered": True, "real_fit_returned_count": 1,
        })
    else:
        registry = Path(json.loads(binding_path.read_text())["official_registry_path"])
        events = [json.loads(line) for line in registry.read_text().splitlines()]
        events[-1]["decision"] = "CANNOT_CONFIRM"
        registry.write_text("".join(json.dumps(event) + "\n" for event in events))
        summary["official_registry_sha256_after_terminal"] = hashlib.sha256(registry.read_bytes()).hexdigest()
        with pytest.raises(EvaluationCompletionError, match=expected):
            write_completion_receipt(spec_path=spec_path, binding_path=binding_path, run_summary=summary)


@pytest.mark.parametrize("mutation", ["stale_event_sha", "previous_sha"])
def test_original_validator_rejects_canonical_chain_tamper_after_outer_receipts_resigned(tmp_path, mutation):
    spec_path, binding_path, paths, summary, _ = _completion_case(tmp_path)
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    registry = Path(binding["official_registry_path"])
    events = [json.loads(line) for line in registry.read_text(encoding="utf-8").splitlines()]
    validator = completion._load_bound_validator(binding)
    builder = validator.OFFICIAL
    terminal = events[-1]
    if mutation == "stale_event_sha":
        terminal["deterministic_metrics"]["fit_call_entered"] = False
    else:
        terminal["previous_event_sha256"] = "f" * 64
        terminal["event_sha256"] = builder._event_sha256(terminal)
    registry.write_bytes(builder._registry_payload(events))
    registry_sha = hashlib.sha256(registry.read_bytes()).hexdigest()
    terminal_receipt = json.loads(paths["terminal_receipt"].read_text(encoding="utf-8"))
    terminal_receipt["official_registry_sha256_after_terminal"] = registry_sha
    terminal_receipt_sha = _write_json(paths["terminal_receipt"], terminal_receipt)
    summary["official_registry_sha256_after_terminal"] = registry_sha
    summary["candidate_terminal_receipt_sha256"] = terminal_receipt_sha
    with pytest.raises(EvaluationCompletionError, match="L04_OFFICIAL_REGISTRY_VALIDATION_FAILED"):
        completion._validated_registry_snapshot(json.loads(binding_path.read_text(encoding="utf-8")))


def test_readback_rejects_post_acceptance_artifact_tamper(tmp_path):
    spec_path, binding_path, paths, summary, _ = _completion_case(tmp_path)
    write_completion_receipt(spec_path=spec_path, binding_path=binding_path, run_summary=summary)
    paths["scores"].write_bytes(b"tampered scores\n")
    with pytest.raises(EvaluationCompletionError, match="L04_COMPLETION_ARTIFACT_SHA_OR_PATH_MISMATCH:scores"):
        read_completion_receipt(
            paths["metrics"].parent / "EVALUATION_COMPLETION_RECEIPT.json",
            spec_path=spec_path,
            binding_path=binding_path,
        )


def test_failure_taxonomy_keeps_optimizer_evaluation_and_engineering_distinct():
    assert classify_failure({"terminal_status": "CANNOT_CONFIRM", "error_type": "INPUT_HASH_MISMATCH"}, {})["failure_phase"] == "ENGINEERING"
    assert classify_failure({"terminal_status": "CANNOT_CONFIRM"}, {"fit_call_entered": True, "real_fit_returned_count": 0})["failure_class"] == "MODEL_OPTIMIZER_FAILURE"
    assert classify_failure({"terminal_status": "CANNOT_CONFIRM"}, {"fit_call_entered": True, "real_fit_returned_count": 1, "evaluation_label_values_decoded": True})["failure_phase"] == "EVALUATION"
