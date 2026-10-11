"""Build and validate the append-only experiment registry.

This file is intentionally a small, data-free skeleton.  Concrete historical
backfill specifications are added in a later, separately reviewed patch.
"""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "workspace"
OUTPUT = ROOT / "contracts" / "EXPERIMENT_REGISTRY.jsonl"

EVENT_SPECS = [
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-WQ101_MASKED_TOKEN_PRENOV_HIST57_HOLDOUT_V1-terminal",
        "execution_id": "backfill-WQ101_MASKED_TOKEN_PRENOV_HIST57_HOLDOUT_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "WQ101_MASKED_TOKEN_PRENOV_HIST57_HOLDOUT_V1",
        "stage": "EVALUATION",
        "event_type": "EVALUATION_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/EXPERIMENT_WQ101_MASKED_TOKEN_HIST57_CONTRACT_20260817.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_masked_token_hist57_holdout/HISTORICAL_EVALUATION.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": 618,
        "one_variable": "frozen_84_wq_masked_token_model",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "OPENED_EXPOSED_HISTORY",
        "sealed_status": "EXPOSED",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "candidate_hits": 609,
            "baseline_hits": 618,
            "truth_positive_denominator": 1140,
            "selection_slots": 5700,
            "daily_wins": 8,
            "daily_ties": 33,
            "daily_losses": 16,
        },
        "decision": "NO_BREAKTHROUGH",
        "stop_reason": "below_619",
        "evidence_level": "DIRECTION_ONLY_ALREADY_EXPOSED_HISTORY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-WQ101_TOKEN_DAILY_LISTNET_PRENOV_HIST57_V1-terminal",
        "execution_id": "backfill-WQ101_TOKEN_DAILY_LISTNET_PRENOV_HIST57_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "WQ101_TOKEN_DAILY_LISTNET_PRENOV_HIST57_V1",
        "stage": "EVALUATION",
        "event_type": "EVALUATION_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/EXPERIMENT_WQ101_TOKEN_LISTNET_HIST57_CONTRACT_20260817.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_token_listnet_hist57_holdout/HISTORICAL_EVALUATION.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": 618,
        "one_variable": "daily_listnet_objective",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "OPENED_EXPOSED_HISTORY",
        "sealed_status": "EXPOSED",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "candidate_hits": 609,
            "baseline_hits": 618,
            "truth_positive_denominator": 1140,
            "selection_slots": 5700,
            "daily_wins": 11,
            "daily_ties": 29,
            "daily_losses": 17,
        },
        "decision": "NO_BREAKTHROUGH",
        "stop_reason": "below_619",
        "evidence_level": "DIRECTION_ONLY_ALREADY_EXPOSED_HISTORY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-HKCONNECT_D1_REACHABLE_CLOSE_TOP20_TRUTH_V1-terminal",
        "execution_id": "backfill-HKCONNECT_D1_REACHABLE_CLOSE_TOP20_TRUTH_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "HKCONNECT_D1_REACHABLE_CLOSE_TOP20_TRUTH_V1",
        "stage": "VALIDATION",
        "event_type": "VALIDATION_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/D1_REACHABLE_CLOSE_TOP20_TRUTH_CONTRACT_20260817.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/d1_reachable_close_top20_truth/20260817/ACCEPTANCE.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": None,
        "one_variable": "D1_reachable_close_top20_truth_repair",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "LABEL_BUILD_OPENED",
        "sealed_status": "FROZEN_DATA_INPUT",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "target_dates": 722,
            "rows": 389133,
            "positives": 14440,
            "positives_per_date": 20,
            "replacements": 70,
            "unreachable_positives": 0,
            "missing_return_rows": 137,
            "truth_positive_denominator": 14440,
            "selection_slots": None,
        },
        "decision": "PASS_D1_REACHABLE_CLOSE_TOP20_TRUTH_FROZEN",
        "stop_reason": "data_dependency_only_not_model_hit",
        "evidence_level": "FEATURE_INFORMATION_FOUND",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-ONLINE_PAST_ONLY_SWAP_VALUE_GATE_FORWARD_20260817_V1-terminal",
        "execution_id": "backfill-ONLINE_PAST_ONLY_SWAP_VALUE_GATE_FORWARD_20260817_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "ONLINE_PAST_ONLY_SWAP_VALUE_GATE_FORWARD_20260817_V1",
        "stage": "PRETRUTH",
        "event_type": "PRETRUTH_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/EXPERIMENT_ONLINE_SWAP_VALUE_FORWARD_CONTRACT_20260817.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/online_swap_value_forward/20260817/PRETRUTH_ACCEPTANCE.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": "ONLINE_PAST_ONLY_SWAP_VALUE_GATE_FULL57_V1",
        "one_variable": "new_signal_date_forward_application",
        "signal_date_range": ["20260814", "20260814"],
        "target_date_range": ["20260817", "20260817"],
        "truth_access": "NOT_OPENED",
        "sealed_status": "FORWARD_PRETRUTH",
        "runtime": None,
        "device": "mps:0",
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "proposed": 9,
            "accepted": 6,
            "truth_positive_denominator": None,
            "selection_slots": 100,
        },
        "decision": "PRETRUTH_FORWARD_RESEARCH_RANKING_ONLY",
        "stop_reason": "await_sealed_truth_no_hit_claim",
        "evidence_level": "DIRECTION_ONLY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-D1_REACHABLE_MASKED_FINANCIAL_FORWARD_20260817_V1-terminal",
        "execution_id": "backfill-D1_REACHABLE_MASKED_FINANCIAL_FORWARD_20260817_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "D1_REACHABLE_MASKED_FINANCIAL_FORWARD_20260817_V1",
        "stage": "PRETRUTH",
        "event_type": "PRETRUTH_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/D1_REACHABLE_MASKED_FINANCIAL_FORWARD_CONTRACT_20260817.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/d1_reachable_masked_financial_forward/20260817/PRETRUTH_ACCEPTANCE.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": 619,
        "one_variable": "D1_truth_plus_masked_financial_coverage",
        "signal_date_range": ["20260814", "20260814"],
        "target_date_range": ["20260817", "20260817"],
        "truth_access": "NOT_OPENED",
        "sealed_status": "FORWARD_PRETRUTH",
        "runtime": None,
        "device": "mps:0",
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "train_rows": 389133,
            "train_dates": 722,
            "positives": 14440,
            "forward_universe": 651,
            "available": 552,
            "missing": 99,
            "proposed": 10,
            "accepted": 5,
            "historical_corrected_meta_candidate": 620,
            "historical_base": 619,
            "truth_positive_denominator": None,
            "selection_slots": 100,
        },
        "decision": "PASS_D1_REACHABLE_MASKED_FINANCIAL_FORWARD_FROZEN",
        "stop_reason": "no_forward_truth_no_hit_claim",
        "evidence_level": "ENGINEERING_CANARY_AND_CORRECTED_META_DIAGNOSTIC_ONLY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-D1_REACHABLE_FULLMARKET_OOF_V1-terminal",
        "execution_id": "backfill-D1_REACHABLE_FULLMARKET_OOF_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "D1_REACHABLE_FULLMARKET_OOF_V1",
        "stage": "OOF",
        "event_type": "EVALUATION_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/D1_REACHABLE_FULLMARKET_OOF_V1_CONTRACT_20260817.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/d1_reachable_fullmarket_oof_v1/HISTORICAL_EVALUATION.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": "D1_RETRAINED_BASE_616",
        "one_variable": "fullmarket_continuous_oof_meta_before_top100",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "OPENED_EXPOSED_HISTORY",
        "sealed_status": "EXPOSED",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "candidate_hits": 617,
            "baseline_hits": 616,
            "legacy_base_hits": 619,
            "corrected_anchor_hits": 620,
            "truth_positive_denominator": 1140,
            "selection_slots": 5700,
            "daily_wins": 11,
            "daily_ties": 31,
            "daily_losses": 15,
            "fullmarket_rows": 34974,
        },
        "decision": "NO_BREAKTHROUGH",
        "stop_reason": "below_619_and_620",
        "evidence_level": "DIRECTION_ONLY_ALREADY_EXPOSED_HISTORY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-D1_TRUE_CLOSE_MEMORY_FULLMARKET_OOF_V1-terminal",
        "execution_id": "backfill-D1_TRUE_CLOSE_MEMORY_FULLMARKET_OOF_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "D1_TRUE_CLOSE_MEMORY_FULLMARKET_OOF_V1",
        "stage": "OOF",
        "event_type": "EVALUATION_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/D1_TRUE_CLOSE_MEMORY_FULLMARKET_OOF_V1_CONTRACT_20260817.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/d1_true_close_memory_fullmarket_oof_v1/HISTORICAL_EVALUATION.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": 610,
        "one_variable": "replace19_recent_top20_with_lagged_d1_close_memory",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "OPENED_EXPOSED_HISTORY",
        "sealed_status": "EXPOSED",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "candidate_hits": 613,
            "baseline_hits": 610,
            "truth_positive_denominator": 1140,
            "selection_slots": 5700,
            "daily_wins": 17,
            "daily_ties": 28,
            "daily_losses": 12,
        },
        "decision": "NO_BREAKTHROUGH",
        "stop_reason": "below619_620",
        "evidence_level": "DIRECTION_ONLY_ALREADY_EXPOSED_HISTORY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-AUTOALPHA_D1_CLOSE_TOP20_QD_V1-terminal",
        "execution_id": "backfill-AUTOALPHA_D1_CLOSE_TOP20_QD_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "AUTOALPHA_D1_CLOSE_TOP20_QD_V1",
        "stage": "SEARCH",
        "event_type": "EVALUATION_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/AUTOALPHA_D1_CLOSE_TOP20_QD_V1_CONTRACT_20260817.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/autoalpha_d1_close_top20_qd_v1/HISTORICAL_EVALUATION.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": 619,
        "one_variable": "metric_blind_non_wq_qd_formula_channel",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "OPENED_EXPOSED_HISTORY",
        "sealed_status": "EXPOSED",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "formula_hits": 575,
            "candidate_fusion_hits": 595,
            "baseline_hits": 619,
            "truth_positive_denominator": 1140,
            "selection_slots": 5700,
        },
        "decision": "NO_BREAKTHROUGH",
        "stop_reason": "below_base_no_retune",
        "evidence_level": "DIRECTION_ONLY_ALREADY_EXPOSED_HISTORY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-AUTOALPHA_D1_CLOSE_TOP20_WQ101_QD_V1-terminal",
        "execution_id": "backfill-AUTOALPHA_D1_CLOSE_TOP20_WQ101_QD_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "AUTOALPHA_D1_CLOSE_TOP20_WQ101_QD_V1",
        "stage": "SEARCH",
        "event_type": "EVALUATION_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/AUTOALPHA_D1_CLOSE_TOP20_WQ101_QD_V1_CONTRACT_20260818.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/autoalpha_d1_close_top20_wq101_qd_v1/HISTORICAL_EVALUATION.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": 619,
        "one_variable": "matched_formula_ab_design",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "OPENED_EXPOSED_HISTORY",
        "sealed_status": "EXPOSED",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "candidate_a_hits": 573,
            "candidate_b_hits": 581,
            "placebo_hits": 627,
            "fusion_hits": 615,
            "selected_wq_formulas": 0,
            "truth_positive_denominator": 1140,
            "selection_slots": 5700,
        },
        "decision": "NO_BREAKTHROUGH",
        "stop_reason": "INVALID_TREATMENT_ZERO_WQ_SELECTED_NOT_VALID_WQ_CONCLUSION",
        "evidence_level": "DIRECTION_ONLY_ALREADY_EXPOSED_HISTORY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-AUTOALPHA_D1_CLOSE_TOP20_WQ101_QD_V2_MATCHED_QUOTA-terminal",
        "execution_id": "backfill-AUTOALPHA_D1_CLOSE_TOP20_WQ101_QD_V2_MATCHED_QUOTA",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "AUTOALPHA_D1_CLOSE_TOP20_WQ101_QD_V2_MATCHED_QUOTA",
        "stage": "SEARCH",
        "event_type": "EVALUATION_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/AUTOALPHA_D1_CLOSE_TOP20_WQ101_QD_V2_CONTRACT_20260818.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/autoalpha_d1_close_top20_wq101_qd_v2/HISTORICAL_EVALUATION.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": 619,
        "one_variable": "strict_matched_wq_quota",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "OPENED_EXPOSED_HISTORY",
        "sealed_status": "EXPOSED",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "candidate_a_hits": 557,
            "candidate_b_hits": 570,
            "placebo_hits": 610,
            "fusion_hits": 596,
            "wq_selected": 2,
            "shared": 6,
            "truth_positive_denominator": 1140,
            "selection_slots": 5700,
        },
        "decision": "NO_BREAKTHROUGH",
        "stop_reason": "B_minus_placebo_minus40_close_v2_not_wq_family",
        "evidence_level": "DIRECTION_ONLY_SELECTION_TAINTED_BY_V1_TREATMENT_REPAIR",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-HKEX_TITLE_SEMANTIC_RESIDUAL_V1-terminal",
        "execution_id": "backfill-HKEX_TITLE_SEMANTIC_RESIDUAL_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "HKEX_TITLE_SEMANTIC_RESIDUAL_V1",
        "stage": "SEARCH",
        "event_type": "EVALUATION_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/HKEX_TITLE_SEMANTIC_RESIDUAL_V1_CONTRACT_20260818.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/hkex_title_semantic_residual_v1/HISTORICAL_EVALUATION.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": "D1_CORRECTED_ANCHOR_620",
        "one_variable": "title_category_hashed_ngram_replace_control7",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "OPENED_EXPOSED_HISTORY",
        "sealed_status": "EXPOSED",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "treatment_hits": 573,
            "anchor_hits": 620,
            "control_hits": 547,
            "placebo_hits": 576,
            "truth_positive_denominator": 1140,
            "selection_slots": 5700,
            "daily_wins": 11,
            "daily_ties": 13,
            "daily_losses": 33,
        },
        "decision": "NO_BREAKTHROUGH",
        "stop_reason": "STOP_CLOSE_ROUTE_NO_RETUNING",
        "evidence_level": "DIRECTION_ONLY_DEVELOPMENT_HISTORY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-WQ101_CAUSAL_USAGE_AUDIT_V1-terminal",
        "execution_id": "backfill-WQ101_CAUSAL_USAGE_AUDIT_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "WQ101_CAUSAL_USAGE_AUDIT_V1",
        "stage": "AUDIT",
        "event_type": "AUDIT_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/WQ101_CAUSAL_USAGE_AUDIT_V1_CONTRACT_20260819.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_causal_usage_audit_v1/AUDIT_RESULT.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": 619,
        "one_variable": "deterministic_causal_usage_controls",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "OPENED_EXPOSED_HISTORY",
        "sealed_status": "EXPOSED",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "pointwise_true": 610,
            "listnet_true": 610,
            "neutral": 619,
            "reverse_pointwise": 608,
            "reverse_listnet": 586,
            "timeshift_pointwise": 614,
            "timeshift_listnet": 594,
            "factor_count": 84,
            "wq_cell_coverage": 0.9745617,
            "truth_positive_denominator": 1140,
            "selection_slots": 5700,
        },
        "decision": "NO_BREAKTHROUGH",
        "stop_reason": "NO_INCREMENTAL_INFORMATION_WIRING_PASS_NOT_WQ_FAMILY_BAN",
        "evidence_level": "DIRECTION_ONLY_ALREADY_EXPOSED_HISTORY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_SWAP_V1-terminal",
        "execution_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_SWAP_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "WQ101_SELECTIVE_UNCERTAINTY_SWAP_V1",
        "stage": "CANARY",
        "event_type": "CANARY_PASS",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/WQ101_SELECTIVE_UNCERTAINTY_SWAP_V1_CONTRACT_20260819.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_swap_v1/ENGINEERING_CANARY.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "baseline_id": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": None,
        "one_variable": "synthetic_shape_mps_canary",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "NOT_OPENED",
        "sealed_status": "ENGINEERING_ONLY",
        "runtime": None,
        "device": "mps:0",
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "synthetic_rows": 12,
            "elapsed_seconds": 0.2368,
            "truth_positive_denominator": None,
            "selection_slots": None,
        },
        "decision": "PASS_ENGINEERING_CANARY",
        "stop_reason": "THREE_SEED_TRAINING_NOT_RUN_V1_1_SUPERSEDES",
        "evidence_level": "ENGINEERING_CANARY_ONLY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_SWAP_V1_1-terminal",
        "execution_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_SWAP_V1_1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "WQ101_SELECTIVE_UNCERTAINTY_SWAP_V1_1",
        "stage": "TRAINING",
        "event_type": "TRAINING_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/WQ101_SELECTIVE_UNCERTAINTY_SWAP_V1_1_CONTRACT_20260819.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_swap_v1_1/TRAINING_LEDGER.json",
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_swap_v1_1/POSTDATE_ENGINEERING_REPLAY.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": "WQ_SWAP_V1_ENGINEERING_ONLY",
        "one_variable": "microbatch512_accumulation4_three_seed_training",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "NOT_OPENED",
        "sealed_status": "PRETRUTH_MODEL_FROZEN",
        "runtime": None,
        "device": "mps:0",
        "checkpoint_ref": "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_swap_v1_1/TRAINING_LEDGER.json",
        "deterministic_metrics": {
            "seeds": 3,
            "epochs_per_seed": 6,
            "effective_batch": 2048,
            "rows_per_seed": 176639,
            "dates": 330,
            "positives_per_seed": 6600,
            "wq_cell_coverage": 0.9813601,
            "elapsed_seconds": 7310.728,
            "replay_universe": 651,
            "replay_top100": 100,
            "replay_swaps": 0,
            "abstained": 551,
            "truth_positive_denominator": None,
            "selection_slots": 100,
        },
        "decision": "COMPLETED_THREE_SEEDS",
        "stop_reason": "AWAIT_SEALED_FORWARD_NOT_HIT_RESULT",
        "evidence_level": "ENGINEERING_CANARY_ONLY_NO_FORWARD_PROOF",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_DAILY_INPUT_V1-terminal",
        "execution_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_DAILY_INPUT_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "WQ101_SELECTIVE_UNCERTAINTY_DAILY_INPUT_V1",
        "stage": "VALIDATION",
        "event_type": "PREFLIGHT_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/WQ101_SELECTIVE_UNCERTAINTY_DAILY_INPUT_V1_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_daily_inputs_v1/PREFLIGHT.json",
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_daily_inputs_v1/signal_inputs_20260820/COLLECTION_MANIFEST.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "baseline_id": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": None,
        "one_variable": "daily_input_maturity_gate",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "NOT_OPENED",
        "sealed_status": "PRETRUTH",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "collection_generated": True,
            "truth_positive_denominator": None,
            "selection_slots": None,
        },
        "decision": "CANNOT_CONFIRM_SIGNAL_CLOSE_DATA_NOT_MATURE_OR_MISSING",
        "stop_reason": "input_maturity_not_confirmed_not_model_result",
        "evidence_level": "CANNOT_CONFIRM",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-FUTU_OPEND_HKCONNECT_SIGNAL_INPUT_V1-terminal",
        "execution_id": "backfill-FUTU_OPEND_HKCONNECT_SIGNAL_INPUT_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "FUTU_OPEND_HKCONNECT_SIGNAL_INPUT_V1",
        "stage": "DATA_COLLECTION",
        "event_type": "DATA_COLLECTION_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/FUTU_OPEND_HKCONNECT_SIGNAL_INPUT_V1_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_daily_inputs_v1/signal_inputs_20260820/COLLECTION_MANIFEST.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "baseline_id": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": None,
        "one_variable": "futu_opend_hkconnect_signal_input_collection",
        "signal_date_range": ["20260820", "20260820"],
        "target_date_range": None,
        "truth_access": "NOT_OPENED",
        "sealed_status": "PRETRUTH_INPUT",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "selector_called": False,
            "truth_opened": False,
            "truth_positive_denominator": None,
            "selection_slots": None,
        },
        "decision": "PASS_SIGNAL_INPUT_COLLECTION",
        "stop_reason": "data_input_only_not_model_result",
        "evidence_level": "FEATURE_INFORMATION_FOUND",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-FUTU_OPEND_HKCONNECT_SIGNAL_INPUT_ROLLING_V2-terminal",
        "execution_id": "backfill-FUTU_OPEND_HKCONNECT_SIGNAL_INPUT_ROLLING_V2",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "FUTU_OPEND_HKCONNECT_SIGNAL_INPUT_ROLLING_V2",
        "stage": "DATA_COLLECTION",
        "event_type": "PREFLIGHT_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/FUTU_OPEND_HKCONNECT_SIGNAL_INPUT_ROLLING_V2_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_daily_inputs_v1/signal_input_rolling_v2/INIT_RECEIPT.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "baseline_id": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": None,
        "one_variable": "rolling_signal_input_chain_init",
        "signal_date_range": ["20260820", "20260820"],
        "target_date_range": None,
        "truth_access": "NOT_OPENED",
        "sealed_status": "PRETRUTH_INPUT",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "chain_rows": 1,
            "opend_calls": 0,
            "quote_calls": 0,
            "selector_called": False,
            "trade_calls": 0,
            "truth_positive_denominator": None,
            "selection_slots": None,
        },
        "decision": "INITIALIZED",
        "stop_reason": "init_only_not_complete_collection_or_model_result",
        "evidence_level": "ENGINEERING_CANARY_ONLY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_DAILY_ANCHOR_V1-terminal",
        "execution_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_DAILY_ANCHOR_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "WQ101_SELECTIVE_UNCERTAINTY_DAILY_ANCHOR_V1",
        "stage": "PRETRUTH",
        "event_type": "PRETRUTH_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/WQ101_SELECTIVE_UNCERTAINTY_DAILY_ANCHOR_V1_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_daily_inputs_v1/anchor_replay_20260817/EXPERT_REPLAY_REPORT.json",
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_daily_inputs_v1/anchor_formal_20260821/ANCHOR_RECEIPT.json",
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_daily_inputs_v1/anchor_preflight_20260821/PREFLIGHT.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": "ONLINE_PAST_ONLY_SWAP_VALUE_GATE_FULL57_V1",
        "one_variable": "daily_anchor_replay_and_formal_freeze",
        "signal_date_range": ["20260820", "20260820"],
        "target_date_range": ["20260821", "20260821"],
        "truth_access": "NOT_OPENED",
        "sealed_status": "FORWARD_PRETRUTH",
        "runtime": None,
        "device": "mps:0",
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "universe": 651,
            "replay_proposed": 9,
            "replay_accepted": 6,
            "formal_proposed": 14,
            "formal_accepted": 7,
            "outcome_metrics": False,
            "truth_positive_denominator": None,
            "selection_slots": 100,
        },
        "decision": "FORMAL_ANCHOR_FROZEN_RESEARCH_ONLY",
        "stop_reason": "formal_preflight_CANNOT_CONFIRM_SIGNAL_CLOSE_DATA_NOT_MATURE_OR_MISSING_not_backtest",
        "evidence_level": "DIRECTION_ONLY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_DAILY_WQ_V1-terminal",
        "execution_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_DAILY_WQ_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "WQ101_SELECTIVE_UNCERTAINTY_DAILY_WQ_V1",
        "stage": "VALIDATION",
        "event_type": "VALIDATION_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/WQ101_SELECTIVE_UNCERTAINTY_DAILY_WQ_V1_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_daily_inputs_v1/wq_replay_20260817/WQ_REPLAY_REPORT.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "baseline_id": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": None,
        "one_variable": "exact_84_wq_feature_replay",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "NOT_OPENED",
        "sealed_status": "PRETRUTH_FEATURE_REPLAY",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "factor_ids": 84,
            "rows": 651,
            "common_finite_cells": 44358,
            "numeric_max_diff": 0,
            "cache_hits": 84,
            "truth_positive_denominator": None,
            "selection_slots": None,
        },
        "decision": "PASS_WQ_REPLAY",
        "stop_reason": "feature_wiring_only_not_alpha_lift",
        "evidence_level": "FEATURE_INFORMATION_FOUND",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_DAILY_WQ_FORMAL_V1-terminal",
        "execution_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_DAILY_WQ_FORMAL_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "WQ101_SELECTIVE_UNCERTAINTY_DAILY_WQ_FORMAL_V1",
        "stage": "PRETRUTH",
        "event_type": "PREFLIGHT_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/WQ101_SELECTIVE_UNCERTAINTY_DAILY_WQ_FORMAL_V1_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_daily_inputs_v1/wq_formal_preflight_20260821/formal_20260821/WQ101_FORMAL_RECEIPT.json",
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_daily_inputs_v1/wq_formal_preflight_20260821/PREFLIGHT.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "baseline_id": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": None,
        "one_variable": "formal_84_wq_panel",
        "signal_date_range": ["20260820", "20260820"],
        "target_date_range": ["20260821", "20260821"],
        "truth_access": "NOT_OPENED",
        "sealed_status": "FORWARD_PRETRUTH",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "factor_ids": 84,
            "outcome_metrics": False,
            "truth_positive_denominator": None,
            "selection_slots": None,
        },
        "decision": "CANNOT_CONFIRM",
        "stop_reason": "RAW_SIGNAL_DATE_NOT_LATEST_BASE_DATE_GATE_FAILED_RAW_SIGNAL_COVERAGE_NOT_EXACT",
        "evidence_level": "CANNOT_CONFIRM",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_FORWARD_SNAPSHOT_V1-terminal",
        "execution_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_FORWARD_SNAPSHOT_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "WQ101_SELECTIVE_UNCERTAINTY_FORWARD_SNAPSHOT_V1",
        "stage": "FORWARD",
        "event_type": "FORWARD_SNAPSHOT_WRITTEN",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/WQ101_SELECTIVE_UNCERTAINTY_FORWARD_SNAPSHOT_V1_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_forward_snapshot_v1/snapshots/20260821_20260820/RECEIPT.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "baseline_id": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": None,
        "one_variable": "frozen_v1_1_forward_snapshot",
        "signal_date_range": ["20260820", "20260820"],
        "target_date_range": ["20260821", "20260821"],
        "truth_access": "NOT_OPENED",
        "sealed_status": "FORWARD_ACTIVE",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "chain_rows": 1,
            "required_rows": 57,
            "universe": 651,
            "swaps": 1,
            "outcome_metrics": False,
            "truth_positive_denominator": None,
            "selection_slots": 100,
        },
        "decision": "SNAPSHOT_WRITTEN",
        "stop_reason": "chain_1_of_57_no_evaluation",
        "evidence_level": "DIRECTION_ONLY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_FORWARD_EVALUATION_V1-terminal",
        "execution_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_FORWARD_EVALUATION_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "WQ101_SELECTIVE_UNCERTAINTY_FORWARD_EVALUATION_V1",
        "stage": "EVALUATION",
        "event_type": "PREFLIGHT_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/WQ101_SELECTIVE_UNCERTAINTY_FORWARD_EVALUATION_V1_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_forward_evaluation_v1/PREFLIGHT.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "baseline_id": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": None,
        "one_variable": "frozen_forward_chain_evaluation_gate",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "NOT_OPENED",
        "sealed_status": "FORWARD_ACTIVE",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "chain_rows": 1,
            "required_rows": 57,
            "truth_columns": [],
            "outcome_metrics": False,
            "truth_positive_denominator": None,
            "selection_slots": None,
        },
        "decision": "CANNOT_CONFIRM_FORWARD_CHAIN_INCOMPLETE",
        "stop_reason": "preflight_only_not_zero_score_or_failed_backtest",
        "evidence_level": "CANNOT_CONFIRM",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_FORWARD_DAILY_COORDINATOR_V1-terminal",
        "execution_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_FORWARD_DAILY_COORDINATOR_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "WQ101_SELECTIVE_UNCERTAINTY_FORWARD_DAILY_COORDINATOR_V1",
        "stage": "VALIDATION",
        "event_type": "PREFLIGHT_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/WQ101_SELECTIVE_UNCERTAINTY_FORWARD_DAILY_COORDINATOR_V1_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_forward_daily_coordinator_v1/CURRENT_PREFLIGHT.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "baseline_id": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": None,
        "one_variable": "daily_forward_orchestration_verification",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "NOT_OPENED",
        "sealed_status": "FORWARD_ACTIVE",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "rolling_chain_rows": 1,
            "snapshot_chain_rows": 1,
            "evaluator_called": False,
            "mps_candidate_invocations": 0,
            "trade_api_calls": 0,
            "truth_opened": False,
            "truth_positive_denominator": None,
            "selection_slots": None,
        },
        "decision": "PASS_VERIFY_CURRENT",
        "stop_reason": "coordinator_preflight_only_not_model_pass",
        "evidence_level": "ENGINEERING_CANARY_ONLY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_OPENBOOK_HIST57_V1-terminal",
        "execution_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_OPENBOOK_HIST57_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "WQ101_SELECTIVE_UNCERTAINTY_OPENBOOK_HIST57_V1",
        "stage": "EVALUATION",
        "event_type": "EVALUATION_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/WQ101_SELECTIVE_UNCERTAINTY_OPENBOOK_HIST57_V1_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_openbook_hist57_v1/OPENBOOK_DIAGNOSTIC.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": "D1_CORRECTED_ANCHOR_620",
        "one_variable": "frozen_v1_1_selective_swap_openbook_hist57",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "OPENED_EXPOSED_HISTORY",
        "sealed_status": "EXPOSED",
        "runtime": None,
        "device": "mps:0",
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "candidate_hits": 616,
            "anchor_hits": 620,
            "truth_positive_denominator": 1140,
            "selection_slots": 5700,
            "candidate_rows": 5700,
            "anchor_rows": 5700,
            "swaps": 158,
            "daily_wins": 5,
            "daily_ties": 44,
            "daily_losses": 8,
        },
        "decision": "NO_BREAKTHROUGH",
        "stop_reason": "below_anchor_not_sealed_forward",
        "evidence_level": "OPENBOOK_DIAGNOSTIC_ONLY_D1_DIRECTION_ONLY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-HKEX_FULLBODY_PIT_CANARY_V1-terminal",
        "execution_id": "backfill-HKEX_FULLBODY_PIT_CANARY_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "HKEX_FULLBODY_PIT_CANARY_V1",
        "stage": "CANARY",
        "event_type": "CANARY_PASS",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/HKEX_FULLBODY_PIT_CANARY_V1_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/hkex_fullbody_pit_canary_v1/RUN_SUMMARY.json",
            "workspace/hk_close_top20_recall_v1_20260813/runs/hkex_fullbody_pit_canary_v1/CACHE_ONLY_VERIFICATION.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "baseline_id": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": None,
        "one_variable": "hkex_fullbody_pit_download_and_cache",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "NOT_OPENED",
        "sealed_status": "DATA_CANARY_ONLY",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "samples": 24,
            "download_success": 24,
            "nonempty": 24,
            "raw_bytes": 1227493,
            "independent_cache_network_requests": 0,
            "identity_sha_matches": 24,
            "raw_sha_matches": 24,
            "text_sha_matches": 24,
            "run_summary_cache_only_verified": False,
            "independent_cache_only_pass": True,
            "truth_positive_denominator": None,
            "selection_slots": None,
        },
        "decision": "DATA_CANARY_READY",
        "stop_reason": "RUN_SUMMARY_CACHE_ONLY_FALSE_CONFLICT_PREVENTS_FULL_DATA_ACCEPTANCE",
        "evidence_level": "ENGINEERING_CANARY_ONLY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-DOUBLEENSEMBLE_DENOISE_V1-26-synthetic-terminal",
        "execution_id": "backfill-DOUBLEENSEMBLE_DENOISE_V1-26-synthetic",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "DOUBLEENSEMBLE_DENOISE_V1",
        "stage": "CANARY",
        "event_type": "CANARY_PASS",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/DOUBLEENSEMBLE_DENOISE_V1_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/doubleensemble_denoise_v1/synthetic_canary/CANARY_SUMMARY.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "baseline_id": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": None,
        "one_variable": "QLIB_SR_FS_DENOISE_TREATMENT",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "NOT_OPENED",
        "sealed_status": "ENGINEERING_ONLY",
        "runtime": None,
        "device": "CPU",
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "first_model_max_abs_diff": 0,
            "strict100": True,
            "real_f1_run": False,
            "truth_read": False,
            "truth_positive_denominator": None,
            "selection_slots": None,
        },
        "decision": "ENGINEERING_CANARY_ONLY",
        "stop_reason": "synthetic_only",
        "evidence_level": "ENGINEERING_CANARY_ONLY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-DOUBLEENSEMBLE_DENOISE_V1-27-f1-terminal",
        "execution_id": "backfill-DOUBLEENSEMBLE_DENOISE_V1-27-f1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "DOUBLEENSEMBLE_DENOISE_V1",
        "stage": "EVALUATION",
        "event_type": "EVALUATION_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/DOUBLEENSEMBLE_DENOISE_V1_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/doubleensemble_denoise_v1/F1/F1_EVALUATION.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": "DOUBLEENSEMBLE_UNIT_WEIGHT_ALL_249_CONTROL",
        "one_variable": "QLIB_SR_FS_DENOISE_TREATMENT",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "OPENED_EXPOSED_HISTORY",
        "sealed_status": "EXPOSED",
        "runtime": None,
        "device": "CPU",
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "control_hits": 552,
            "candidate_hits": 557,
            "truth_positive_denominator": 1260,
            "selection_slots_per_arm": 6300,
            "selection_slots": 12600,
            "daily_wins": 25,
            "daily_ties": 16,
            "daily_losses": 22,
            "fold_result": "WIN",
        },
        "decision": "PASS_F1_DOUBLE_GATE_EVIDENCE_ONLY",
        "stop_reason": "continue_sequential_fold_gate",
        "evidence_level": "OPENBOOK_HISTORICAL_DIAGNOSTIC_ONLY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-DOUBLEENSEMBLE_DENOISE_V1-28-f2-terminal",
        "execution_id": "backfill-DOUBLEENSEMBLE_DENOISE_V1-28-f2",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "DOUBLEENSEMBLE_DENOISE_V1",
        "stage": "EVALUATION",
        "event_type": "EVALUATION_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/DOUBLEENSEMBLE_DENOISE_V1_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/doubleensemble_denoise_v1/F2/F2_EVALUATION.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": "DOUBLEENSEMBLE_UNIT_WEIGHT_ALL_249_CONTROL",
        "one_variable": "QLIB_SR_FS_DENOISE_TREATMENT",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "OPENED_EXPOSED_HISTORY",
        "sealed_status": "EXPOSED",
        "runtime": None,
        "device": "CPU",
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "control_hits": 631,
            "candidate_hits": 624,
            "truth_positive_denominator": 1240,
            "selection_slots_per_arm": 6200,
            "selection_slots": 12400,
            "daily_wins": 18,
            "daily_ties": 24,
            "daily_losses": 20,
            "fold_result": "LOSS",
        },
        "decision": "NO_FOLD_LIFT",
        "stop_reason": "first_fold_loss_continue_until_two_losses",
        "evidence_level": "OPENBOOK_HISTORICAL_DIAGNOSTIC_ONLY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-DOUBLEENSEMBLE_DENOISE_V1-29-f3-terminal",
        "execution_id": "backfill-DOUBLEENSEMBLE_DENOISE_V1-29-f3",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "DOUBLEENSEMBLE_DENOISE_V1",
        "stage": "EVALUATION",
        "event_type": "EVALUATION_COMPLETED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/DOUBLEENSEMBLE_DENOISE_V1_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/doubleensemble_denoise_v1/F3/F3_EVALUATION.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": "DOUBLEENSEMBLE_UNIT_WEIGHT_ALL_249_CONTROL",
        "one_variable": "QLIB_SR_FS_DENOISE_TREATMENT",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "OPENED_EXPOSED_HISTORY",
        "sealed_status": "EXPOSED",
        "runtime": None,
        "device": "CPU",
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "control_hits": 625,
            "candidate_hits": 640,
            "truth_positive_denominator": 1200,
            "selection_slots_per_arm": 6000,
            "selection_slots": 12000,
            "daily_wins": 24,
            "daily_ties": 22,
            "daily_losses": 14,
            "fold_result": "WIN",
            "cumulative_control_hits": 1808,
            "cumulative_candidate_hits": 1821,
            "cumulative_truth_positive_denominator": 3700,
        },
        "decision": "FOLD_WIN_NOT_BREAKTHROUGH",
        "stop_reason": "continue_sequence_gate",
        "evidence_level": "OPENBOOK_HISTORICAL_DIAGNOSTIC_ONLY",
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "backfill-DOUBLEENSEMBLE_DENOISE_V1-30-f4-terminal",
        "execution_id": "backfill-DOUBLEENSEMBLE_DENOISE_V1-30-f4",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "BACKFILLED_FROM_ARTIFACT",
        "route_id": "DOUBLEENSEMBLE_DENOISE_V1",
        "stage": "EVALUATION",
        "event_type": "EARLY_STOPPED",
        "occurred_at": None,
        "occurred_at_reason": "HISTORICAL_ARTIFACT_DOES_NOT_PROVE_EXACT_EVENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/DOUBLEENSEMBLE_DENOISE_V1_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/doubleensemble_denoise_v1/F4/F4_EVALUATION.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": "DOUBLEENSEMBLE_UNIT_WEIGHT_ALL_249_CONTROL",
        "one_variable": "QLIB_SR_FS_DENOISE_TREATMENT",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "OPENED_EXPOSED_HISTORY",
        "sealed_status": "EXPOSED",
        "runtime": None,
        "device": "CPU",
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "control_hits": 628,
            "candidate_hits": 616,
            "truth_positive_denominator": 1200,
            "selection_slots_per_arm": 6000,
            "selection_slots": 12000,
            "daily_wins": 17,
            "daily_ties": 19,
            "daily_losses": 24,
            "fold_result": "LOSS",
            "cumulative_control_hits": 2436,
            "cumulative_candidate_hits": 2437,
            "cumulative_truth_positive_denominator": 4900,
            "cumulative_daily_wins": 84,
            "cumulative_daily_ties": 81,
            "cumulative_daily_losses": 80,
            "fold_wins": 2,
            "fold_ties": 0,
            "fold_losses": 2,
            "planned_total_denominator": 6600,
            "evaluated_denominator": 4900,
            "f5_run": False,
            "aggregate_generated": False,
        },
        "decision": "NO_BREAKTHROUGH",
        "stop_reason": "EARLY_STOP_FULL_PASS_IMPOSSIBLE",
        "evidence_level": "OPENBOOK_HISTORICAL_DIAGNOSTIC_ONLY",
    },
]
EXPECTED_MIN_EVENTS = 30
EXPECTED_MIN_ROUTES = 26
EXPECTED_MIN_EXECUTIONS = 30
# Backwards-compatible aliases for callers that imported the old constants.
EXPECTED_EVENTS = EXPECTED_MIN_EVENTS
EXPECTED_ROUTES = EXPECTED_MIN_ROUTES
CORRECTION_SPECS = [
    {
        "schema_version": "1.0",
        "registry_event_id": "correction-20260821-ONLINE_PAST_ONLY_SWAP_VALUE_GATE_FORWARD_20260817_V1-metadata",
        "execution_id": "backfill-ONLINE_PAST_ONLY_SWAP_VALUE_GATE_FORWARD_20260817_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "APPENDED_CORRECTION",
        "route_id": "ONLINE_PAST_ONLY_SWAP_VALUE_GATE_FORWARD_20260817_V1",
        "stage": "PRETRUTH",
        "event_type": "CORRECTION",
        "occurred_at": None,
        "occurred_at_reason": "ADMINISTRATIVE_CORRECTION_TIME_NOT_USED_AS_EXPERIMENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/EXPERIMENT_ONLINE_SWAP_VALUE_FORWARD_CONTRACT_20260817.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/online_swap_value_forward/20260817/PRETRUTH_ACCEPTANCE.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": "ONLINE_PAST_ONLY_SWAP_VALUE_GATE_FULL57_V1",
        "one_variable": "new_signal_date_forward_application",
        "signal_date_range": ["20260814", "20260814"],
        "target_date_range": ["20260817", "20260817"],
        "truth_access": "NOT_OPENED",
        "sealed_status": "FORWARD_PRETRUTH",
        "runtime": None,
        "device": "mps:0",
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "proposed": 9,
            "accepted": 6,
            "truth_positive_denominator": None,
            "selection_slots": 100,
            "corrects_registry_event_id": "backfill-ONLINE_PAST_ONLY_SWAP_VALUE_GATE_FORWARD_20260817_V1-terminal",
            "corrects_event_sha256": "495ad17f6387d0d5d5a55de9c80d94f8501863c89ad4fa78e219bbf8837ce0dc",
            "corrected_fields": ["evidence_level"],
        },
        "decision": "PRETRUTH_FORWARD_RESEARCH_RANKING_ONLY",
        "stop_reason": "metadata_only_no_metric_or_model_change",
        "evidence_level": "ENGINEERING_CANARY_ONLY",
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "correction-20260821-WQ101_SELECTIVE_UNCERTAINTY_DAILY_ANCHOR_V1-metadata",
        "execution_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_DAILY_ANCHOR_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "APPENDED_CORRECTION",
        "route_id": "WQ101_SELECTIVE_UNCERTAINTY_DAILY_ANCHOR_V1",
        "stage": "PRETRUTH",
        "event_type": "CORRECTION",
        "occurred_at": None,
        "occurred_at_reason": "ADMINISTRATIVE_CORRECTION_TIME_NOT_USED_AS_EXPERIMENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/WQ101_SELECTIVE_UNCERTAINTY_DAILY_ANCHOR_V1_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_daily_inputs_v1/anchor_replay_20260817/EXPERT_REPLAY_REPORT.json",
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_daily_inputs_v1/anchor_formal_20260821/ANCHOR_RECEIPT.json",
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_daily_inputs_v1/anchor_preflight_20260821/PREFLIGHT.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": "ONLINE_PAST_ONLY_SWAP_VALUE_GATE_FULL57_V1",
        "one_variable": "daily_anchor_replay_and_formal_freeze",
        "signal_date_range": ["20260820", "20260820"],
        "target_date_range": ["20260821", "20260821"],
        "truth_access": "NOT_OPENED",
        "sealed_status": "FORWARD_PRETRUTH",
        "runtime": None,
        "device": "mps:0",
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "universe": 651,
            "replay_proposed": 9,
            "replay_accepted": 6,
            "formal_proposed": 14,
            "formal_accepted": 7,
            "outcome_metrics": False,
            "truth_positive_denominator": None,
            "selection_slots": 100,
            "corrects_registry_event_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_DAILY_ANCHOR_V1-terminal",
            "corrects_event_sha256": "612f0103930099f5f6f10ab8e4f6df636e4972ed21efff331a39d0b8a09bc990",
            "corrected_fields": ["evidence_level"],
        },
        "decision": "FORMAL_ANCHOR_FROZEN_RESEARCH_ONLY",
        "stop_reason": "metadata_only_no_metric_or_model_change",
        "evidence_level": "ENGINEERING_CANARY_ONLY",
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "correction-20260821-WQ101_SELECTIVE_UNCERTAINTY_FORWARD_SNAPSHOT_V1-metadata",
        "execution_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_FORWARD_SNAPSHOT_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "APPENDED_CORRECTION",
        "route_id": "WQ101_SELECTIVE_UNCERTAINTY_FORWARD_SNAPSHOT_V1",
        "stage": "FORWARD",
        "event_type": "CORRECTION",
        "occurred_at": None,
        "occurred_at_reason": "ADMINISTRATIVE_CORRECTION_TIME_NOT_USED_AS_EXPERIMENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/WQ101_SELECTIVE_UNCERTAINTY_FORWARD_SNAPSHOT_V1_CONTRACT_20260820.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/wq101_selective_uncertainty_forward_snapshot_v1/snapshots/20260821_20260820/RECEIPT.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "baseline_id": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": None,
        "one_variable": "frozen_v1_1_forward_snapshot",
        "signal_date_range": ["20260820", "20260820"],
        "target_date_range": ["20260821", "20260821"],
        "truth_access": "NOT_OPENED",
        "sealed_status": "FORWARD_ACTIVE",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "chain_rows": 1,
            "required_rows": 57,
            "universe": 651,
            "swaps": 1,
            "outcome_metrics": False,
            "truth_positive_denominator": None,
            "selection_slots": 100,
            "corrects_registry_event_id": "backfill-WQ101_SELECTIVE_UNCERTAINTY_FORWARD_SNAPSHOT_V1-terminal",
            "corrects_event_sha256": "54cc60a27369de8413b2ba528d24c3c954ce79babc73b982998a345420cca993",
            "corrected_fields": ["evidence_level"],
        },
        "decision": "SNAPSHOT_WRITTEN",
        "stop_reason": "metadata_only_no_metric_or_model_change",
        "evidence_level": "ENGINEERING_CANARY_ONLY",
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    },
    {
        "schema_version": "1.0",
        "registry_event_id": "correction-20260821-AUTOALPHA_D1_CLOSE_TOP20_WQ101_QD_V1-metadata",
        "execution_id": "backfill-AUTOALPHA_D1_CLOSE_TOP20_WQ101_QD_V1",
        "track_id": "HK_OHLCV_FULLMARKET_TOP100",
        "registration_mode": "APPENDED_CORRECTION",
        "route_id": "AUTOALPHA_D1_CLOSE_TOP20_WQ101_QD_V1",
        "stage": "SEARCH",
        "event_type": "CORRECTION",
        "occurred_at": None,
        "occurred_at_reason": "ADMINISTRATIVE_CORRECTION_TIME_NOT_USED_AS_EXPERIMENT_TIME",
        "contract_path": "workspace/hk_close_top20_recall_v1_20260813/AUTOALPHA_D1_CLOSE_TOP20_WQ101_QD_V1_CONTRACT_20260818.json",
        "artifact_paths": [
            "workspace/hk_close_top20_recall_v1_20260813/runs/autoalpha_d1_close_top20_wq101_qd_v1/HISTORICAL_EVALUATION.json",
        ],
        "input_identity": {
            "null_reasons": {
                "input_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "code_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "config_sha256": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "signal_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "target_date_range": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "runtime": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "device": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
                "checkpoint_ref": "NOT_DIRECTLY_PROVEN_BY_MAIN_ARTIFACT",
            }
        },
        "input_sha256": None,
        "code_sha256": None,
        "config_sha256": None,
        "baseline_id": 619,
        "one_variable": "matched_formula_ab_design",
        "signal_date_range": None,
        "target_date_range": None,
        "truth_access": "OPENED_EXPOSED_HISTORY",
        "sealed_status": "EXPOSED",
        "runtime": None,
        "device": None,
        "checkpoint_ref": None,
        "deterministic_metrics": {
            "candidate_a_hits": 573,
            "candidate_b_hits": 581,
            "placebo_hits": 627,
            "fusion_hits": 615,
            "selected_wq_formulas": 0,
            "truth_positive_denominator": 1140,
            "selection_slots": 5700,
            "corrects_registry_event_id": "backfill-AUTOALPHA_D1_CLOSE_TOP20_WQ101_QD_V1-terminal",
            "corrects_event_sha256": "1d159c09d74c22b4e66e823d87bde164ed7742cc5507a585f5e88b6a7a7d715c",
            "corrected_fields": ["decision"],
        },
        "decision": "INVALID_TREATMENT",
        "stop_reason": "metadata_only_no_metric_or_model_change",
        "evidence_level": "DIRECTION_ONLY_ALREADY_EXPOSED_HISTORY",
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    },
]

ZERO_SHA256 = "0" * 64
SAFETY_FLAGS = {
    "research_only": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}

# These names mirror the minimum event fields in the project registry
# contract.  A value may be null only when its reason is recorded in
# input_identity.null_reasons; the chain and safety fields are never nullable.
REQUIRED_FIELDS = (
    "schema_version",
    "registry_event_id",
    "registration_mode",
    "route_id",
    "execution_id",
    "track_id",
    "stage",
    "event_type",
    "occurred_at",
    "occurred_at_reason",
    "contract_path",
    "contract_sha256",
    "input_identity",
    "input_sha256",
    "code_sha256",
    "config_sha256",
    "baseline_id",
    "one_variable",
    "signal_date_range",
    "target_date_range",
    "truth_access",
    "sealed_status",
    "runtime",
    "device",
    "artifact_path",
    "artifact_sha256",
    "checkpoint_ref",
    "deterministic_metrics",
    "decision",
    "stop_reason",
    "evidence_level",
    "research_only",
    "production_allowed",
    "buy_gate_updated",
    "orders_sent",
    "previous_event_sha256",
    "event_sha256",
)


def _canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _event_sha256(event):
    payload = {key: value for key, value in event.items() if key != "event_sha256"}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def sha256_file(path):
    """Return the SHA-256 digest of one explicitly named file."""

    digest = hashlib.sha256()
    with pathlib.Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_value(value):
    if isinstance(value, dict):
        value = value.get("path")
    if value is None:
        raise ValueError("PATH_VALUE_REQUIRED")
    return pathlib.Path(value)


def _resolved_file(value, label):
    path = _path_value(value)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}:{path}")
    return path


def _display_path(value):
    if isinstance(value, dict):
        value = value.get("path")
    return str(value)


def _path_values(value):
    if isinstance(value, (str, pathlib.Path, dict)):
        return [value]
    if isinstance(value, (list, tuple)):
        return list(value)
    raise TypeError("PATH_COLLECTION_REQUIRED")


def _artifact_values(spec):
    value = spec.get("artifact_paths")
    if value is None:
        value = spec.get("artifacts")
    if value is None:
        value = spec.get("artifact_path")
    if value is None:
        raise KeyError("artifact_path(s) is required")
    values = _path_values(value)
    if not values:
        raise ValueError("AT_LEAST_ONE_ARTIFACT_REQUIRED")
    return values


def _sha_from_declared_or_paths(spec, sha_key, path_keys):
    if sha_key in spec:
        return spec[sha_key]
    for path_key in path_keys:
        if path_key in spec and spec[path_key] is not None:
            values = _path_values(spec[path_key])
            hashes = [sha256_file(_resolved_file(value, path_key)) for value in values]
            return hashes[0] if len(hashes) == 1 else hashes
    return None


def _null_reasons(event, input_identity):
    reasons = input_identity.get("null_reasons", {})
    if reasons is None:
        reasons = {}
    if not isinstance(reasons, dict):
        raise TypeError("input_identity.null_reasons must be an object")

    # A spec may carry a stale or broad reason map.  Keep only reasons for
    # values that are still null after all derived fields and safety flags
    # have been materialized; newly materialized events must not claim a
    # reason for a value that is present.
    for field in list(reasons):
        if field.startswith("deterministic_metrics."):
            metric_field = field.split(".", 1)[1]
            metrics = event.get("deterministic_metrics")
            if isinstance(metrics, dict) and metrics.get(metric_field) is not None:
                reasons.pop(field, None)
        elif event.get(field) is not None:
            reasons.pop(field, None)

    for field in REQUIRED_FIELDS:
        if field in {"event_sha256", "previous_event_sha256"}:
            continue
        if event.get(field) is None:
            reasons.setdefault(field, "NOT_PROVIDED_IN_EVENT_SPEC")

    for field, value in event.items():
        if field in {"event_sha256", "previous_event_sha256"}:
            continue
        if value is None:
            reasons.setdefault(field, "NOT_PROVIDED_IN_EVENT_SPEC")

    metrics = event.get("deterministic_metrics")
    if isinstance(metrics, dict):
        for field in ("truth_positive_denominator", "selection_slots"):
            if metrics.get(field) is None:
                reasons.setdefault(
                    f"deterministic_metrics.{field}",
                    "NOT_PROVIDED_IN_EVENT_SPEC",
                )
    input_identity["null_reasons"] = reasons
    return input_identity


def _materialize(specs, starting_previous_sha):
    """Materialize specs, optionally continuing from an existing chain SHA."""

    events = []
    previous_sha = starting_previous_sha
    for index, spec in enumerate(specs):
        if not isinstance(spec, dict):
            raise TypeError(f"EVENT_SPEC_NOT_OBJECT:{index}")

        contract_value = spec.get("contract_path", spec.get("contract"))
        if contract_value is None:
            raise KeyError(f"contract_path is required:{index}")
        contract_path = _resolved_file(contract_value, "contract")
        artifact_values = _artifact_values(spec)
        artifact_paths = [
            _resolved_file(value, "artifact") for value in artifact_values
        ]

        # Preserve explicit event metadata while excluding source aliases and
        # chain values that this function must derive itself.
        source_only = {
            "contract",
            "contract_path",
            "artifact",
            "artifacts",
            "artifact_path",
            "artifact_paths",
            "input_path",
            "input_paths",
            "code_path",
            "code_paths",
            "config_path",
            "config_paths",
            "event_sha256",
            "previous_event_sha256",
            "safety_flags",
        }
        event = {
            key: value for key, value in spec.items() if key not in source_only
        }
        event["contract_path"] = _display_path(contract_value)
        event["contract_sha256"] = sha256_file(contract_path)

        displayed_artifacts = [_display_path(value) for value in artifact_values]
        actual_artifacts = [sha256_file(path) for path in artifact_paths]
        if len(displayed_artifacts) == 1:
            event["artifact_path"] = displayed_artifacts[0]
            event["artifact_sha256"] = actual_artifacts[0]
        else:
            event["artifact_path"] = displayed_artifacts
            event["artifact_sha256"] = actual_artifacts

        event["input_sha256"] = _sha_from_declared_or_paths(
            spec, "input_sha256", ("input_path", "input_paths")
        )
        event["code_sha256"] = _sha_from_declared_or_paths(
            spec, "code_sha256", ("code_path", "code_paths")
        )
        event["config_sha256"] = _sha_from_declared_or_paths(
            spec, "config_sha256", ("config_path", "config_paths")
        )

        if "checkpoint_ref" not in event:
            event["checkpoint_ref"] = spec.get("checkpoint")
        metrics = event.get("deterministic_metrics")
        if metrics is None:
            metrics = {}
        if not isinstance(metrics, dict):
            raise TypeError(f"deterministic_metrics must be an object:{index}")
        metrics = dict(metrics)
        metrics.setdefault("truth_positive_denominator", None)
        metrics.setdefault("selection_slots", None)
        event["deterministic_metrics"] = metrics

        input_identity = event.get("input_identity")
        if input_identity is None:
            input_identity = {}
        if not isinstance(input_identity, dict):
            raise TypeError(f"input_identity must be an object:{index}")
        input_identity = dict(input_identity)
        if isinstance(input_identity.get("null_reasons"), dict):
            input_identity["null_reasons"] = dict(input_identity["null_reasons"])

        declared_safety = dict(spec.get("safety_flags") or {})
        for field, expected in SAFETY_FLAGS.items():
            value = spec.get(field, declared_safety.get(field, expected))
            if value is not expected:
                raise ValueError(f"UNSAFE_SAFETY_FLAG:{field}")
            event[field] = expected

        for field in REQUIRED_FIELDS:
            event.setdefault(field, None)
        event["previous_event_sha256"] = previous_sha
        event["input_identity"] = _null_reasons(event, input_identity)
        event["event_sha256"] = _event_sha256(event)
        events.append(event)
        previous_sha = event["event_sha256"]

    _validate_event_list(
        events,
        starting_previous_sha=starting_previous_sha,
        enforce_minimums=False,
        validate_corrections=False,
    )
    return events


def materialize(specs, starting_previous_sha=ZERO_SHA256):
    """Materialize specs, optionally continuing from an existing chain SHA."""

    return _materialize(specs, starting_previous_sha)


@contextlib.contextmanager
def _exclusive_registry_lock():
    """Serialize registry creation and append operations with an fcntl lock."""

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    lock_path = OUTPUT.with_name(f".{OUTPUT.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _registry_payload(events):
    return "".join(_canonical_json(event) + "\n" for event in events).encode("utf-8")


def write_registry(events):
    """Create the registry once, or no-op on identical canonical content."""

    _validate_event_list(events)
    payload = _registry_payload(events)
    with _exclusive_registry_lock():
        if OUTPUT.exists():
            if OUTPUT.read_bytes() == payload:
                return
            raise RuntimeError("APPEND_ONLY_REGISTRY_EXISTS_DIFFERENT_CONTENT")

        temp_fd, temp_name = tempfile.mkstemp(
            prefix=f".{OUTPUT.name}.", suffix=".tmp", dir=str(OUTPUT.parent)
        )
        try:
            with os.fdopen(temp_fd, "wb") as handle:
                temp_fd = None
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if OUTPUT.exists():
                raise RuntimeError("APPEND_ONLY_REGISTRY_EXISTS_DIFFERENT_CONTENT")
            os.replace(temp_name, OUTPUT)
            temp_name = None
        finally:
            if temp_fd is not None:
                os.close(temp_fd)
            if temp_name is not None:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass


def _validate_event(event, previous_sha, index):
    if not isinstance(event, dict):
        raise ValueError(f"EVENT_NOT_OBJECT:{index}")
    missing = [field for field in REQUIRED_FIELDS if field not in event]
    if missing:
        raise ValueError(f"REQUIRED_FIELDS_MISSING:{index}:{','.join(missing)}")
    for field in (
        "schema_version",
        "registry_event_id",
        "registration_mode",
        "execution_id",
    ):
        if not isinstance(event[field], str) or not event[field]:
            raise ValueError(f"IDENTITY_FIELD_INVALID:{index}:{field}")

    input_identity = event["input_identity"]
    if not isinstance(input_identity, dict):
        raise ValueError(f"INPUT_IDENTITY_INVALID:{index}")
    null_reasons = input_identity.get("null_reasons", {})
    if not isinstance(null_reasons, dict):
        raise ValueError(f"NULL_REASONS_INVALID:{index}")
    for field in REQUIRED_FIELDS:
        if field in {"event_sha256", "previous_event_sha256"}:
            continue
        if event[field] is None and field not in null_reasons:
            raise ValueError(f"NULL_REASON_MISSING:{index}:{field}")

    for field, expected in SAFETY_FLAGS.items():
        if event[field] is not expected:
            raise ValueError(f"SAFETY_FLAG_INVALID:{index}:{field}")
    metrics = event["deterministic_metrics"]
    if not isinstance(metrics, dict):
        raise ValueError(f"DETERMINISTIC_METRICS_INVALID:{index}")
    for field in ("truth_positive_denominator", "selection_slots"):
        if field not in metrics:
            raise ValueError(f"DETERMINISTIC_METRIC_MISSING:{index}:{field}")
        if metrics[field] is None and f"deterministic_metrics.{field}" not in null_reasons:
            raise ValueError(f"NULL_REASON_MISSING:{index}:deterministic_metrics.{field}")

    if event["previous_event_sha256"] != previous_sha:
        raise ValueError(f"PREVIOUS_HASH_INVALID:{index}")
    event_sha = event["event_sha256"]
    if not isinstance(event_sha, str) or len(event_sha) != 64:
        raise ValueError(f"EVENT_HASH_INVALID:{index}")
    try:
        int(event_sha, 16)
    except ValueError as exc:
        raise ValueError(f"EVENT_HASH_INVALID:{index}") from exc
    if event_sha != _event_sha256(event):
        raise ValueError(f"EVENT_HASH_INVALID:{index}")


LIFECYCLE_EVENT_MARKERS = (
    "ABORT",
    "CANCEL",
    "CHECKPOINT",
    "CANNOT_CONFIRM",
    "COMPLETED",
    "CORRECTION",
    "EARLY_STOP",
    "FAIL",
    "INTERRUPT",
    "PROGRESS",
    "RUN_",
    "STOP",
    "TIE",
)


def _execution_reuse_allowed(event):
    # A terminal event is the canonical lifecycle close marker.  Match the
    # event type exactly: adding TERMINAL to the substring marker list would
    # accidentally admit names such as NON_TERMINAL_METADATA.
    if event.get("event_type") == "TERMINAL":
        return True
    values = (
        event.get("registration_mode"),
        event.get("stage"),
        event.get("event_type"),
    )
    haystack = "|".join(str(value or "").upper() for value in values)
    return any(marker in haystack for marker in LIFECYCLE_EVENT_MARKERS)


def _validate_correction_event(event, prior_events_by_sha, index):
    metrics = event["deterministic_metrics"]
    is_correction = (
        event.get("registration_mode") == "APPENDED_CORRECTION"
        or event.get("event_type") == "CORRECTION"
        or "corrects_event_sha256" in metrics
        or "corrects_registry_event_id" in metrics
    )
    if not is_correction:
        return
    if event.get("registration_mode") != "APPENDED_CORRECTION":
        raise ValueError(f"CORRECTION_REGISTRATION_MODE_INVALID:{index}")
    if event.get("event_type") != "CORRECTION":
        raise ValueError(f"CORRECTION_EVENT_TYPE_INVALID:{index}")
    corrected_event_id = metrics.get("corrects_registry_event_id")
    corrected_event_sha = metrics.get("corrects_event_sha256")
    corrected_fields = metrics.get("corrected_fields")
    if not isinstance(corrected_event_id, str) or not corrected_event_id:
        raise ValueError(f"CORRECTION_TARGET_ID_INVALID:{index}")
    if not isinstance(corrected_event_sha, str) or len(corrected_event_sha) != 64:
        raise ValueError(f"CORRECTION_TARGET_SHA_INVALID:{index}")
    if not isinstance(corrected_fields, list) or not corrected_fields:
        raise ValueError(f"CORRECTION_FIELDS_INVALID:{index}")
    if not all(isinstance(field, str) and field for field in corrected_fields):
        raise ValueError(f"CORRECTION_FIELDS_INVALID:{index}")
    target = prior_events_by_sha.get(corrected_event_sha)
    if target is None:
        raise ValueError(f"CORRECTION_TARGET_NOT_EARLIER:{index}:{corrected_event_sha}")
    if target.get("registry_event_id") != corrected_event_id:
        raise ValueError(f"CORRECTION_TARGET_ID_MISMATCH:{index}")
    if target.get("route_id") != event.get("route_id"):
        raise ValueError(f"CORRECTION_ROUTE_ID_MISMATCH:{index}")
    if target.get("execution_id") != event.get("execution_id"):
        raise ValueError(f"CORRECTION_EXECUTION_ID_MISMATCH:{index}")


def _validate_event_list(
    events,
    starting_previous_sha=ZERO_SHA256,
    enforce_minimums=True,
    validate_corrections=True,
):
    """Validate an in-memory chain, including future append-only events."""

    previous_sha = starting_previous_sha
    registry_event_ids = set()
    execution_ids = {}
    prior_events_by_sha = {}
    for index, event in enumerate(events):
        _validate_event(event, previous_sha, index)
        if validate_corrections:
            _validate_correction_event(event, prior_events_by_sha, index)
        registry_event_id = event["registry_event_id"]
        if registry_event_id in registry_event_ids:
            raise ValueError(f"REGISTRY_EVENT_ID_DUPLICATE:{index}:{registry_event_id}")
        registry_event_ids.add(registry_event_id)

        execution_id = event["execution_id"]
        if execution_id in execution_ids and not _execution_reuse_allowed(event):
            raise ValueError(f"EXECUTION_ID_REUSE_NOT_LIFECYCLE:{index}:{execution_id}")
        execution_ids.setdefault(execution_id, index)
        prior_events_by_sha[event["event_sha256"]] = event
        previous_sha = event["event_sha256"]

    if not enforce_minimums:
        return events

    if len(events) < EXPECTED_MIN_EVENTS:
        raise ValueError(f"EVENT_COUNT_BELOW_MINIMUM:{len(events)}:{EXPECTED_MIN_EVENTS}")
    actual_route_ids = {event["route_id"] for event in events}
    if len(actual_route_ids) < EXPECTED_MIN_ROUTES:
        raise ValueError(
            f"ROUTE_COUNT_BELOW_MINIMUM:{len(actual_route_ids)}:{EXPECTED_MIN_ROUTES}"
        )
    expected_route_ids = {spec["route_id"] for spec in EVENT_SPECS}
    if not expected_route_ids.issubset(actual_route_ids):
        raise ValueError("BASE_ROUTE_ID_SET_NOT_SUBSET")
    if len(execution_ids) < EXPECTED_MIN_EXECUTIONS:
        raise ValueError(
            "EXECUTION_COUNT_BELOW_MINIMUM:"
            f"{len(execution_ids)}:{EXPECTED_MIN_EXECUTIONS}"
        )
    return events


def _read_registry_events():
    if not OUTPUT.is_file():
        raise FileNotFoundError(str(OUTPUT))
    raw = OUTPUT.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError("REGISTRY_NOT_NEWLINE_TERMINATED")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("REGISTRY_NOT_UTF8") from exc

    events = []
    for index, line in enumerate(text.splitlines()):
        if not line.strip():
            raise ValueError(f"BLANK_REGISTRY_LINE:{index}")
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"INVALID_REGISTRY_JSON:{index}") from exc
        if _canonical_json(event) != line:
            raise ValueError(f"NON_CANONICAL_REGISTRY_LINE:{index}")
        events.append(event)
    return events


def check_registry():
    """Validate the existing registry, or acknowledge the empty skeleton."""

    if not OUTPUT.is_file():
        if EXPECTED_MIN_EVENTS == 0 and EXPECTED_MIN_ROUTES == 0:
            print("SKELETON_READY")
            return []
        raise FileNotFoundError(str(OUTPUT))

    events = _read_registry_events()
    _validate_event_list(events)
    if EXPECTED_MIN_EVENTS == 0 and EXPECTED_MIN_ROUTES == 0:
        print("SKELETON_READY")
    else:
        print("REGISTRY_CHECK_PASS")
    return events


def append_corrections():
    """Append a complete correction batch without rewriting existing bytes."""

    with _exclusive_registry_lock():
        events = _read_registry_events()
        _validate_event_list(events)
        existing_ids = {event["registry_event_id"] for event in events}
        correction_ids = []
        for index, spec in enumerate(CORRECTION_SPECS):
            registry_event_id = spec.get("registry_event_id")
            if not isinstance(registry_event_id, str) or not registry_event_id:
                raise ValueError(f"CORRECTION_REGISTRY_EVENT_ID_INVALID:{index}")
            correction_ids.append(registry_event_id)
        if len(correction_ids) != len(set(correction_ids)):
            raise ValueError("CORRECTION_REGISTRY_EVENT_ID_DUPLICATE")

        present = [registry_event_id in existing_ids for registry_event_id in correction_ids]
        if not correction_ids:
            print("CORRECTIONS_NOOP")
            return events
        if all(present):
            print("CORRECTIONS_ALREADY_PRESENT")
            return events
        if any(present):
            raise RuntimeError("PARTIAL_CORRECTION_SET_PRESENT")

        previous_sha = events[-1]["event_sha256"] if events else ZERO_SHA256
        corrections = materialize(
            CORRECTION_SPECS,
            starting_previous_sha=previous_sha,
        )
        combined = events + corrections
        _validate_event_list(combined)
        raw = OUTPUT.read_bytes()
        if raw and not raw.endswith(b"\n"):
            raise ValueError("REGISTRY_NOT_NEWLINE_TERMINATED")
        with OUTPUT.open("ab") as handle:
            handle.write(_registry_payload(corrections))
            handle.flush()
            os.fsync(handle.fileno())
        print("CORRECTIONS_APPENDED")
        return combined


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="materialize EVENT_SPECS and then validate the registry",
    )
    parser.add_argument(
        "--append-corrections",
        action="store_true",
        help="append the complete CORRECTION_SPECS batch under an exclusive lock",
    )
    args = parser.parse_args()
    if args.write and args.append_corrections:
        parser.error("--write and --append-corrections are mutually exclusive")
    if args.write:
        write_registry(materialize(EVENT_SPECS))
        check_registry()
    elif args.append_corrections:
        append_corrections()
    else:
        check_registry()


if __name__ == "__main__":
    main()
