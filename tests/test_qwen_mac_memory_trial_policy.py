#!/usr/bin/env python3
"""Offline regression checks for fail-closed trial policy helpers."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


DRIVER_PATH = Path(__file__).resolve().parents[1] / "ops" / "run_qwen_mac_memory_trial.py"
SPEC = importlib.util.spec_from_file_location("live_trial_driver_under_test", DRIVER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("LIVE_TRIAL_DRIVER_IMPORT_FAILED")
DRIVER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DRIVER
SPEC.loader.exec_module(DRIVER)


def activity(phase: str, sample_id: str | None = None, active: int = 0, waiting: int = 0) -> dict[str, object]:
    return {
        "activity_phase": phase,
        "activity_sample_id": sample_id,
        "active_requests": active,
        "waiting_requests": waiting,
        "activity_counts_status": "MEASURED",
    }


class _JsonResponse:
    def __init__(self, payload: object, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self._payload


class _ActivityClient:
    def __init__(self, payload: object):
        self.payload = payload
        self.paths: list[str] = []

    def get(self, path: str, *, timeout: float) -> _JsonResponse:
        self.paths.append(path)
        return _JsonResponse(self.payload)


class AdminActivityShapeTests(unittest.TestCase):
    def test_observed_nested_active_models_shape_measures_zero_counts(self) -> None:
        # Sanitized live receipt showed top-level {"active_models": ...}; this
        # fixture keeps only its two integer counters, not the full response.
        client = _ActivityClient({"active_models": {
            "total_active_requests": 0,
            "total_waiting_requests": 0,
        }})

        result = DRIVER._read_admin_activity(client)

        self.assertEqual(client.paths, [DRIVER.ADMIN_ACTIVITY_PATH])
        self.assertEqual(result["activity_counts_status"], "MEASURED")
        self.assertEqual(result["active_requests"], 0)
        self.assertEqual(result["waiting_requests"], 0)

    def test_missing_or_invalid_counters_remain_unavailable_and_fail_closed(self) -> None:
        cases = [
            {},
            {"active_models": {}},
            {"active_models": {"total_active_requests": 0}},
            {"active_models": {"total_active_requests": "0", "total_waiting_requests": 0}},
            {"active_models": {"total_active_requests": -1, "total_waiting_requests": 0}},
            {"active_models": {"total_active_requests": False, "total_waiting_requests": 0}},
            {
                "active_models": {"total_active_requests": "0", "total_waiting_requests": 0},
                "total_active_requests": 0,
                "total_waiting_requests": 0,
            },
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                result = DRIVER._read_admin_activity(_ActivityClient(payload))
                self.assertEqual(result["activity_counts_status"], "CANNOT_CONFIRM")
                self.assertEqual(DRIVER._idle_activity_status(result), "CANNOT_CONFIRM")
                self.assertTrue(
                    result["active_requests"] != 0 or result["waiting_requests"] != 0,
                    "unknown counters must not satisfy the preflight's zero-count gate",
                )

    def test_existing_wrapper_and_legacy_counter_shapes_remain_supported(self) -> None:
        for payload in (
            {"active": 0, "waiting": 0},
            {"total_active_requests": 0, "total_waiting_requests": 0},
        ):
            with self.subTest(payload=payload):
                result = DRIVER._read_admin_activity(_ActivityClient(payload))
                self.assertEqual(result["activity_counts_status"], "MEASURED")
                self.assertEqual(result["active_requests"], 0)
                self.assertEqual(result["waiting_requests"], 0)


class ActivityIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = [
            activity("sequence_start"),
            activity("between_samples", "short"),
            activity("request_in_flight", "short", active=1),
            activity("between_samples", "short"),
            activity("request_in_flight", "table", active=0),
            activity("between_samples", "table"),
            activity("sequence_end"),
        ]

    def test_single_active_count_is_unassigned_without_exclusive_claim(self) -> None:
        result = DRIVER._activity_integrity_summary(self.rows, ["short", "table"])
        self.assertEqual(result["serial_activity_integrity_status"], "PASS_OBSERVED_SERIAL_COUNTS")
        self.assertEqual(result["request_ownership"], "CANNOT_CONFIRM_AGGREGATE_COUNTS_DO_NOT_IDENTIFY_REQUEST")
        self.assertEqual(result["in_flight_active_one_observed_samples_unassigned"], ["short"])
        self.assertEqual(result["in_flight_single_request_observed_samples_unassigned"], ["short"])

    def test_single_waiting_or_active_count_is_unassigned_but_overlap_fails(self) -> None:
        waiting = self.rows + [activity("request_in_flight", "table", waiting=1)]
        waiting_result = DRIVER._activity_integrity_summary(waiting, ["short", "table"])
        self.assertEqual(waiting_result["serial_activity_integrity_status"], "PASS_OBSERVED_SERIAL_COUNTS")
        self.assertEqual(waiting_result["in_flight_single_request_observed_samples_unassigned"], ["short", "table"])
        self.assertEqual(waiting_result["request_ownership"], "CANNOT_CONFIRM_AGGREGATE_COUNTS_DO_NOT_IDENTIFY_REQUEST")
        multiple = self.rows + [activity("request_in_flight", "table", active=1, waiting=1)]
        self.assertEqual(DRIVER._activity_integrity_summary(multiple, ["short", "table"])["serial_activity_integrity_status"], "FAIL")

    def test_unknown_or_invalid_in_flight_counts_cannot_confirm(self) -> None:
        unknown = [dict(row) for row in self.rows]
        unknown[2]["activity_counts_status"] = "CANNOT_CONFIRM"
        invalid = [dict(row) for row in self.rows]
        invalid[2]["active_requests"] = True
        self.assertEqual(DRIVER._activity_integrity_summary(unknown, ["short", "table"])["serial_activity_integrity_status"], "CANNOT_CONFIRM")
        self.assertEqual(DRIVER._activity_integrity_summary(invalid, ["short", "table"])["serial_activity_integrity_status"], "CANNOT_CONFIRM")

    def test_sampler_accepts_one_aggregate_in_flight_request_without_ownership_claim(self) -> None:
        sampler = DRIVER.LiveTelemetrySampler(client=None, output_path=Path("unused"), process_identity=None)
        waiting_row = activity("request_in_flight", "memory", active=0, waiting=1)
        sampler._record_activity_integrity(waiting_row)
        self.assertIsNone(sampler.activity_failure_reason)
        self.assertIsNone(sampler.activity_cannot_reason)
        overlap_row = activity("request_in_flight", "memory", active=1, waiting=1)
        sampler._record_activity_integrity(overlap_row)
        self.assertEqual(sampler.activity_failure_reason, "MULTIPLE_REQUESTS_DURING_SERIAL_CANARY")

    def test_nonzero_boundary_activity_fails(self) -> None:
        polluted = self.rows + [activity("between_samples", "table", active=1)]
        self.assertEqual(DRIVER._activity_integrity_summary(polluted, ["short", "table"])["serial_activity_integrity_status"], "FAIL")

    def test_missing_request_or_end_coverage_cannot_confirm(self) -> None:
        missing_request = DRIVER._activity_integrity_summary(self.rows, ["short", "table", "memory"])
        missing_end = DRIVER._activity_integrity_summary(self.rows[:-1], ["short", "table"])
        self.assertEqual(missing_request["serial_activity_integrity_status"], "CANNOT_CONFIRM")
        self.assertEqual(missing_end["serial_activity_integrity_status"], "CANNOT_CONFIRM")


class SampleOrderAuthorizationTests(unittest.TestCase):
    def _scope(self, authorized_order: tuple[str, ...]) -> dict[str, object]:
        return {
            "phase": "B_EXECUTE_AUTHORIZED",
            "phase_b_authorization": {
                "schema": DRIVER.PHASE_B_AUTH_SCHEMA,
                "status": "AUTHORIZED",
                "phase_a_scope_sha256": DRIVER.PHASE_A_SCOPE_SHA256,
                "reviewer_receipt_sha256": "0" * 64,
                "authorization_id": "unit-test-authorization",
                "authorized_actions": ["run_serial_sequence"],
                "authorized_fraction_values": [1.0],
                "authorized_sample_order": list(authorized_order),
                "stage": "B1_BASELINE",
            },
        }

    def test_default_order_stays_all_three_and_memory_only_requires_exact_order(self) -> None:
        self.assertEqual(DRIVER.SAMPLE_ORDER, ("baseline_short_success", "baseline_table_success", "memory_rejection"))
        self.assertEqual(DRIVER.MEMORY_REJECTION_ORDER, ("memory_rejection",))
        DRIVER._phase_b_auth(self._scope(DRIVER.SAMPLE_ORDER), action="run_serial_sequence", fraction=1.0)
        DRIVER._phase_b_auth(
            self._scope(DRIVER.MEMORY_REJECTION_ORDER),
            action="run_serial_sequence",
            fraction=1.0,
            sample_order=DRIVER.MEMORY_REJECTION_ORDER,
        )
        with self.assertRaises(DRIVER.TrialError) as caught:
            DRIVER._phase_b_auth(
                self._scope(DRIVER.SAMPLE_ORDER),
                action="run_serial_sequence",
                fraction=1.0,
                sample_order=DRIVER.MEMORY_REJECTION_ORDER,
            )
        self.assertEqual(str(caught.exception), "PHASE_B_SAMPLE_ORDER_NOT_AUTHORIZED")
        with self.assertRaises(DRIVER.TrialError) as caught:
            DRIVER._run_sequence(1.0, sample_order=("baseline_short_success", "memory_rejection"))
        self.assertEqual(str(caught.exception), "PHASE_B_SAMPLE_ORDER_INVALID")


class ReloadPolicyTests(unittest.TestCase):
    def test_only_verified_reload_or_unloaded_manual_load_is_accepted(self) -> None:
        self.assertEqual(
            DRIVER._reload_action(
                requires_reload=True,
                auto_reloaded=True,
                reload_deferred=False,
                model_state={"loaded": True, "is_loading": False},
            ),
            "AUTO_RELOAD_VERIFIED_READY",
        )
        self.assertEqual(
            DRIVER._reload_action(
                requires_reload=True,
                auto_reloaded=False,
                reload_deferred=False,
                model_state={"loaded": False, "is_loading": False},
            ),
            "AUTHORIZED_MANUAL_LOAD_REQUIRED",
        )

    def test_deferred_old_or_unverified_engine_state_fails_closed(self) -> None:
        cases = [
            ({"requires_reload": True, "auto_reloaded": False, "reload_deferred": True, "model_state": {"loaded": False, "is_loading": False}}, "ENGINE_RELOAD_DEFERRED"),
            ({"requires_reload": True, "auto_reloaded": False, "reload_deferred": False, "model_state": {"loaded": True, "is_loading": False}}, "ENGINE_RELOAD_NOT_CONFIRMED_OLD_ENGINE_POSSIBLE"),
            ({"requires_reload": True, "auto_reloaded": True, "reload_deferred": False, "model_state": {"loaded": False, "is_loading": False}}, "AUTO_RELOAD_NOT_CONFIRMED_READY"),
        ]
        for kwargs, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(DRIVER.TrialError) as caught:
                    DRIVER._reload_action(**kwargs)
                self.assertEqual(str(caught.exception), expected_code)

    def test_admin_readback_must_include_boolean_load_state(self) -> None:
        payload = {"models": [{"id": DRIVER.MODEL_ID, "settings": {DRIVER.TARGET_FIELD: 1.0}}]}
        with self.assertRaises(DRIVER.TrialError) as caught:
            DRIVER._extract_model_row(payload)
        self.assertEqual(str(caught.exception), "ADMIN_MODEL_LOAD_STATE_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
