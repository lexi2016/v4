from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import httpx

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import announcement_queue as queue_module
import automatic_canary_server as app
import batch_runner as runner
import build_length_canary as length_canary
import test_batch_runner as fixtures


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sse(chunks: list[dict[str, Any]], *, crlf: bool = False) -> bytes:
    separator = "\r\n" if crlf else "\n"
    payload = "".join("data: " + json.dumps(value, ensure_ascii=False) + separator + separator for value in chunks)
    return (payload + "data: [DONE]" + separator + separator).encode("utf-8")


def queue_payload() -> dict[str, Any]:
    batch = fixtures.synthetic_batch()
    article = batch["articles"][0]
    metadata = article["article_metadata"]
    return {
        **{name: article[name] for name in ("article_id", "source_sha256", "body_sha256", "article_body")},
        "date": metadata["publication_date"],
        "market": "HK",
        "prompt_sha256": sha(b"prompt"),
        "model_id": app.MODEL_ID,
        "configuration_sha256": sha(b"config"),
        "rules": app.ARTICLE_RULES,
        "role": app.ARTICLE_ROLE,
        "stage": app.ARTICLE_STAGE,
        "article_metadata": metadata,
    }


def fake_plan(root: Path, *, article_count: int = 1) -> app.FrozenPlan:
    records = []
    article_rows = []
    canary_ids = []
    for i in range(article_count):
        article_id = f"TEST:SYNTH-{i}:HK.{2000 + i:05d}"
        key = sha(article_id.encode())
        records.append({
            "article_id": article_id,
            "article_metadata": {"title": f"fixture {i}"},
        })
        article_rows.append({
            "article_id": article_id,
            "idempotency_key": key,
            "context_admission": "READY",
            "prompt_tokens_exact": 100,
        })
        canary_ids.append(article_id)
    return app.FrozenPlan(
        records=tuple(records),
        cohorts={"canary_A_and_B_union": tuple(canary_ids), "pressure_batch_03": ()},
        metadata={
            "articles": article_rows,
            "input_manifest_sha256": sha(b"manifest"),
            "fixed_fact_extraction_elapsed_by_article": {article_id: 0.0 for article_id in canary_ids},
        },
        manifest_path=root / "automatic-input-manifest.json",
    )


def phase_plan(root: Path) -> app.FrozenPlan:
    base = fake_plan(root, article_count=34)
    article_ids = tuple(row["article_id"] for row in base.metadata["articles"])
    return app.FrozenPlan(
        records=base.records,
        cohorts={
            "canary_A_and_B_union": article_ids[:6],
            "pressure_batch_03": (article_ids[0], *article_ids[6:]),
        },
        metadata=base.metadata,
        manifest_path=base.manifest_path,
    )


class EmptyQueue:
    def __init__(self, root: Path, items: list[dict[str, Any]] | None = None, results: list[dict[str, Any]] | None = None):
        self.state_root = root
        self.items = items or []
        self.results = list(results or [])
        self.run_calls = 0

    def snapshot(self) -> dict[str, Any]:
        counts = {name: 0 for name in queue_module.STATUSES}
        for item in self.items:
            counts[item["status"]] += 1
        return {"items": self.items, "status_counts": counts}

    def run_next(self, executor, validator, **kwargs):
        self.run_calls += 1
        return self.results.pop(0) if self.results else None


class PhaseTrackingQueue:
    def __init__(self, root: Path, plan: app.FrozenPlan):
        self.state_root = root
        self.queue_id = "phase-test-queue"
        self.items = [
            {
                "article_id": row["article_id"],
                "idempotency_key": row["idempotency_key"],
                "status": "PENDING",
                "attempt_count": 0,
                "max_attempts": 2,
                "last_error": None,
                "raw_path": None,
                "raw_sha256": None,
                "validated_sha256": None,
                "attempts": [],
            }
            for row in plan.metadata["articles"]
        ]
        self.by_key = {item["idempotency_key"]: item for item in self.items}
        self.run_calls = 0
        self.executed_keys: list[str] = []

    def snapshot(self) -> dict[str, Any]:
        counts = {name: 0 for name in queue_module.STATUSES}
        for item in self.items:
            counts[item["status"]] += 1
        return {"items": self.items, "status_counts": counts}

    def run_next(self, executor, validator, **kwargs):
        self.run_calls += 1
        allowed = kwargs.get("idempotency_keys")
        item = next((x for x in self.items if x["status"] == "PENDING" and (allowed is None or x["idempotency_key"] in allowed)), None)
        if item is None:
            return None
        item["status"] = "SUCCEEDED"
        item["attempt_count"] += 1
        item["raw_sha256"] = sha(b"fixture raw")
        item["validated_sha256"] = sha(b"fixture validated")
        item["attempts"].append({"duration_seconds": 0.01})
        self.executed_keys.append(item["idempotency_key"])
        return item


class AutomaticCanaryServerTests(unittest.TestCase):
    def test_ui_metric_label_uses_first_nonempty_content_delta(self) -> None:
        self.assertIn("TTFC（首个非空内容）", app.HTML)
        self.assertIn("s.current.ttfc_seconds", app.HTML)
        self.assertNotIn("ttft_seconds", app.HTML)

    def test_ui_exposes_script_model_attempt_and_whole_canary_wall_times(self) -> None:
        self.assertIn("脚本时间", app.HTML)
        self.assertIn("固定事实预处理", app.HTML)
        self.assertIn("模型时间", app.HTML)
        self.assertIn("单篇尝试总时间", app.HTML)
        self.assertIn("canary_elapsed_seconds", app.HTML)
        self.assertIn("canary_script_preflight_elapsed_seconds", app.HTML)
        self.assertIn("canary_execution_wall_seconds", app.HTML)
        self.assertIn("fixed_fact_ledger_sha256", app.HTML)
        self.assertIn("184.731", app.HTML)

    def test_only_stable_error_codes_reach_ui(self) -> None:
        self.assertEqual(app._stable_failure_code(RuntimeError("secret-bearing error text"), "MODEL_REQUEST_FAILED"), "MODEL_REQUEST_FAILED")
        self.assertEqual(app._stable_failure_code(runner.TransportError("CHAT_NO_PROGRESS_TIMEOUT:ReadTimeout"), "MODEL_REQUEST_FAILED"), "CHAT_NO_PROGRESS_TIMEOUT")

    def test_new_simple_workflow_plan_counts_all_34_and_starts_a_fresh_pending_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_root = Path(temp) / "evidence"
            limits = runner.load_runtime_limits()
            plan = app.build_frozen_plan(
                source_dir=app.SOURCE_DIR,
                length_manifest_path=app.LENGTH_MANIFEST,
                output_root=output_root,
                runtime_limits=limits,
            )
            manifest = json.loads(plan.manifest_path.read_text())
            queue = queue_module.SerialAnnouncementQueue(
                output_root / "queue-state" / plan.metadata["queue_id"],
                plan.metadata["queue_id"],
                app.MODEL_ID,
                max_attempts=app.MAX_ATTEMPTS,
            )
            queue_snapshot = queue.snapshot()
        self.assertEqual(manifest["deduped_union_count"], 34)
        canary = set(manifest["cohorts"]["canary_A_and_B_union"]["article_ids"])
        pressure = set(manifest["cohorts"]["pressure_batch_03"]["article_ids"])
        self.assertEqual(len(canary), 6)
        self.assertEqual(len(pressure), 29)
        self.assertEqual(len(canary & pressure), 1)
        self.assertEqual(len(manifest["articles"]), 34)
        self.assertEqual(manifest["runtime_limits"]["context_limit_tokens"], 262144)
        self.assertEqual(manifest["request_policy"]["max_completion_tokens"], 32768)
        self.assertEqual(manifest["request_policy"]["sampling_policy"], app.SIMPLE_WORKFLOW_SAMPLING_POLICY)
        self.assertEqual(
            manifest["request_policy"]["sampling_policy_sha256"],
            app.EXPECTED_SIMPLE_WORKFLOW_SAMPLING_POLICY_SHA256,
        )
        self.assertEqual(
            sha(app.canonical_json(manifest["request_policy"]["sampling_policy"])),
            app.EXPECTED_SIMPLE_WORKFLOW_SAMPLING_POLICY_SHA256,
        )
        self.assertEqual(manifest["request_policy"]["sampling_policy"]["request_temperature"], 0.0)
        self.assertEqual(manifest["request_policy"]["sampling_policy"]["global_config_temperature"], 1.0)
        self.assertTrue(all(
            row["request_sampling_policy_sha256"] == app.EXPECTED_SIMPLE_WORKFLOW_SAMPLING_POLICY_SHA256
            for row in manifest["articles"]
        ))
        self.assertTrue(all(
            f"+request-sampling-policy:{app.EXPECTED_SIMPLE_WORKFLOW_SAMPLING_POLICY_SHA256}"
            in item["identity"]["rules"]
            for item in queue_snapshot["items"]
        ))
        self.assertEqual(manifest["prompt_profile"], runner.SIMPLE_WORKFLOW_PROFILE)
        self.assertEqual(manifest["system_prompt_sha256"], app.EXPECTED_SYSTEM_PROMPT_SHA256)
        self.assertEqual(manifest["source_span_protocol"], runner.SOURCE_SPAN_PROTOCOL)
        self.assertEqual(manifest["source_span_max_codepoints"], runner.SOURCE_SPAN_MAX_CODEPOINTS)
        self.assertEqual(manifest["source_range_protocol"], runner.SOURCE_RANGE_PROTOCOL)
        self.assertEqual(manifest["source_range_single_protocol"], runner.SOURCE_RANGE_SINGLE_PROTOCOL)
        self.assertEqual(manifest["tool_schema_sha256"], sha(runner.canonical_json_bytes(runner.make_tool_schema(app.PROFILE))))
        self.assertEqual(manifest["structured_output_schema_sha256"], sha(runner.canonical_json_bytes(runner.build_simple_workflow_schema(runner.load_active_contract()))))
        self.assertEqual(manifest["runtime_settings_sha256"], app.EXPECTED_SETTINGS_SHA256)
        self.assertEqual(manifest["model_settings_sha256"], app.EXPECTED_MODEL_SETTINGS_SHA256)
        self.assertIn("first non-empty content delta", manifest["request_policy"]["ttfc"])
        self.assertIn("184.731", manifest["request_policy"]["pressure_gate_timing"])
        self.assertIn("fixed-fact extraction for its six articles", manifest["request_policy"]["pressure_gate_timing"])
        self.assertIn("per-attempt ledger verification", manifest["request_policy"]["script_model_timing"])
        baseline = json.loads(app.BASELINE_MANIFEST.read_text())
        self.assertEqual(
            manifest["cohorts"],
            {
                key: {"article_ids": value["article_ids"], "unique_count": value["unique_count"]}
                for key, value in baseline["cohorts"].items()
            },
        )
        self.assertEqual(
            manifest["source_population"]["cohort_authority_manifest_sha256"],
            app.EXPECTED_BASELINE_MANIFEST_SHA256,
        )
        self.assertEqual(
            manifest["source_population"]["native_pressure_batch_03_import_sha256"],
            app.EXPECTED_NATIVE_PRESSURE_BATCH_03_IMPORT_SHA256,
        )
        self.assertTrue(plan.metadata["queue_id"].startswith("simple-workflow-thinking-off-20261014-"))
        self.assertEqual(len(queue_snapshot["items"]), 34)
        self.assertEqual(queue_snapshot["status_counts"]["PENDING"], 34)
        self.assertEqual(sum(item["attempt_count"] for item in queue_snapshot["items"]), 0)
        self.assertEqual(len({row["idempotency_key"] for row in manifest["articles"]}), 34)
        self.assertTrue(all(row["source_span_map_sha256"] for row in manifest["articles"]))
        self.assertTrue(all(row["source_unit_map_sha256"] for row in manifest["articles"]))
        self.assertEqual(manifest["fixed_fact_parser_protocol"], app.EXPECTED_FIXED_FACT_PARSER_PROTOCOL)
        self.assertEqual(manifest["fixed_fact_parser_sha256"], app.EXPECTED_FIXED_FACT_PARSER_SHA256)
        self.assertTrue(all(row["fixed_fact_ledger_sha256"] for row in manifest["articles"]))
        self.assertTrue(all(row["fixed_fact_parser_sha256"] == app.EXPECTED_FIXED_FACT_PARSER_SHA256 for row in manifest["articles"]))
        baseline_rows = {row["article_id"]: row for row in baseline["articles"]}
        v5_manifest = json.loads((app.PIPELINE_DIR / "evidence" / "simple-workflow-20261014" / "compact-v5-evidence-first" / "automatic-input-manifest.json").read_text())
        v5_rows = {row["article_id"]: row for row in v5_manifest["articles"]}
        self.assertEqual(manifest["cohorts"], v5_manifest["cohorts"])
        for row in manifest["articles"]:
            self.assertEqual(row["source_sha256"], baseline_rows[row["article_id"]]["source_sha256"])
            self.assertEqual(row["body_sha256"], baseline_rows[row["article_id"]]["body_sha256"])
            for identity_field in ("source_sha256", "body_sha256", "source_span_map_sha256", "source_unit_map_sha256"):
                self.assertEqual(row[identity_field], v5_rows[row["article_id"]][identity_field], identity_field)
        self.assertIn("disabled explicitly", manifest["request_policy"]["thinking"])
        self.assertIn("thinking_budget omitted", manifest["request_policy"]["thinking"])
        old_manifest = json.loads((app.PIPELINE_DIR / "evidence" / "simple-workflow-20261014" / "compact-v1" / "automatic-input-manifest.json").read_text())
        self.assertTrue({row["idempotency_key"] for row in old_manifest["articles"]}.isdisjoint(
            {row["idempotency_key"] for row in manifest["articles"]}
        ))
        self.assertNotEqual(plan.metadata["queue_id"], "simple-workflow-20261014-693a423c96ca3ed0")
        for row in manifest["articles"]:
            self.assertEqual(row["max_completion_tokens"], 32768)
            self.assertGreater(row["prompt_tokens_exact"], 0)
            self.assertEqual(
                row["context_admission"],
                "READY" if row["prompt_tokens_exact"] + 32768 <= row["context_limit_tokens"] else "CONTEXT_ITEM_UNFIT",
            )
        self.assertEqual(manifest["context_rejections"], [])

    def test_simple_workflow_profile_has_a_fresh_root_and_preserves_old_profile_hashes(self) -> None:
        contract = runner.load_active_contract()
        prior_span = runner.build_system_prompt(contract, "decision_source_span")
        prior_range = runner.build_system_prompt(contract, "decision_source_range")
        prior_range_single = runner.build_system_prompt(contract, "decision_source_range_single")
        prompt = runner.build_system_prompt(contract, runner.SIMPLE_WORKFLOW_PROFILE)
        self.assertEqual(sha(prior_span.encode("utf-8")), "ebd2eb46eae08e48bcf1f137c52b8e795c133a9b70d25b57544f89f7622b9356")
        self.assertEqual(sha(prior_range.encode("utf-8")), "329f49a38f703bfb65162406aa1f662bb18058bec8d9a74f5e4b0e4b4bd0b850")
        self.assertEqual(sha(prior_range_single.encode("utf-8")), app.PREVIOUS_SYSTEM_PROMPT_SHA256)
        self.assertEqual(sha(prompt.encode("utf-8")), app.EXPECTED_SYSTEM_PROMPT_SHA256)
        self.assertEqual(app.PROFILE, runner.SIMPLE_WORKFLOW_PROFILE)
        self.assertEqual(app.EVIDENCE_ROOT.name, "final-candidate")
        self.assertEqual(app.EVIDENCE_ROOT.parent.name, "compact-v9-greedy-judgment")
        self.assertEqual(app.EVIDENCE_ROOT.parent.parent.name, "simple-workflow-20261014")
        self.assertEqual(app.EVIDENCE_ROOT.parent.parent.parent.name, "evidence")
        self.assertEqual(app.PREVIOUS_PROFILE, "decision_source_range_single")
        self.assertNotEqual(app.PREVIOUS_SYSTEM_PROMPT_SHA256, app.EXPECTED_SYSTEM_PROMPT_SHA256)
        self.assertEqual(app.SOURCE_SPAN_BASELINE_PROFILE, "decision_source_span")
        self.assertEqual(app.SOURCE_SPAN_BASELINE_SYSTEM_PROMPT_SHA256, "ebd2eb46eae08e48bcf1f137c52b8e795c133a9b70d25b57544f89f7622b9356")
        superseded_unrun_root = app.PIPELINE_DIR / "evidence" / "source-range-single-20261014"
        self.assertTrue((superseded_unrun_root / "automatic-input-manifest.json").is_file())
        self.assertNotEqual(app.EVIDENCE_ROOT, superseded_unrun_root)

    def test_native_pressure_import_identity_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            wrong_import = Path(temp) / "native-import.json"
            wrong_import.write_bytes(b"different frozen import")
            with (
                mock.patch.object(app, "NATIVE_PRESSURE_BATCH_03_IMPORT", wrong_import),
                mock.patch.object(length_canary, "load_source_population", side_effect=AssertionError("must fail before population load")),
            ):
                with self.assertRaisesRegex(app.PlanError, "NATIVE_PRESSURE_BATCH_03_IMPORT_SHA_MISMATCH"):
                    app.build_frozen_plan(runtime_limits={
                        "context_limit_tokens": 262144,
                        "completion_max_tokens": 32768,
                    })

    def test_canary_pauses_for_explicit_pressure_gate_and_persists_across_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = phase_plan(root)
            queue = PhaseTrackingQueue(root / "queue-state", plan)

            class MockTransport:
                def close(self):
                    return None

            def make_controller():
                return app.AutomaticCanaryController(
                    plan,
                    queue=queue,
                    activity_probe=lambda: (0, 0),
                    model_ready_probe=lambda: True,
                    api_key="unit-secret",
                    transport_factory=lambda *_args: MockTransport(),
                )

            controller = make_controller()
            server = app.create_server(controller)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            client = httpx.Client(trust_env=False)

            def post(current_server, path: str, body: dict[str, Any]) -> httpx.Response:
                url = f"http://127.0.0.1:{current_server.server_address[1]}"
                return client.post(
                    url + path,
                    json=body,
                    headers={"Origin": url, "X-Canary-CSRF": current_server.canary_csrf_token},
                )

            try:
                before_canary = post(server, "/api/approve-pressure", {"confirmation": app.PRESSURE_CONFIRMATION_PHRASE})
                self.assertEqual(before_canary.status_code, 409)
                self.assertEqual(queue.executed_keys, [])

                started = post(server, "/api/start", {})
                self.assertEqual(started.status_code, 202)
                controller._worker.join(timeout=5)
                self.assertFalse(controller._worker.is_alive())
                canary_state = controller.snapshot()
                self.assertEqual(canary_state["state"], "WAITING_QUALITY_REVIEW")
                self.assertEqual(canary_state["phases"]["canary_A_and_B_union"], "WAITING_QUALITY_REVIEW")
                self.assertEqual(canary_state["phase_progress"]["canary_A_and_B_union"]["succeeded"], 6)
                self.assertEqual(canary_state["phases"]["pressure_batch_03"], "NOT_STARTED")
                self.assertEqual(len(queue.executed_keys), 6)
                self.assertEqual(queue.run_calls, 7)  # Six completions and one drain check.

                duplicate_start = post(server, "/api/start", {})
                self.assertEqual(duplicate_start.status_code, 409)
                self.assertEqual(len(queue.executed_keys), 6)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            restarted = make_controller()
            persisted = restarted.snapshot()
            self.assertEqual(persisted["state"], "WAITING_QUALITY_REVIEW")
            self.assertTrue(persisted["pressure_gate_available"])
            self.assertFalse(persisted["pressure_gate_accepted"])
            self.assertEqual(len(queue.executed_keys), 6)

            server2 = app.create_server(restarted)
            thread2 = threading.Thread(target=server2.serve_forever, daemon=True)
            thread2.start()
            try:
                no_implicit_pressure = post(server2, "/api/start", {})
                self.assertEqual(no_implicit_pressure.status_code, 409)
                self.assertEqual(len(queue.executed_keys), 6)
                wrong_confirmation = post(server2, "/api/approve-pressure", {"confirmation": "run pressure"})
                self.assertEqual(wrong_confirmation.status_code, 409)
                self.assertEqual(len(queue.executed_keys), 6)
                accepted = post(server2, "/api/approve-pressure", {"confirmation": app.PRESSURE_CONFIRMATION_PHRASE})
                self.assertEqual(accepted.status_code, 202)
                restarted._worker.join(timeout=5)
                self.assertFalse(restarted._worker.is_alive())
                pressure_state = restarted.snapshot()
                self.assertEqual(pressure_state["state"], "PRESSURE_FINISHED")
                self.assertTrue(pressure_state["pressure_gate_accepted"])
                self.assertEqual(pressure_state["phase_progress"]["pressure_batch_03"]["succeeded"], 29)
                self.assertEqual(pressure_state["phase_progress"]["pressure_batch_03"]["reused_successes"], 1)
                self.assertEqual(len(queue.executed_keys), 34)
                overlap_key = plan.metadata["articles"][0]["idempotency_key"]
                self.assertEqual(queue.executed_keys.count(overlap_key), 1)
                total_before_duplicate = queue.run_calls
                duplicate_gate = post(server2, "/api/approve-pressure", {"confirmation": app.PRESSURE_CONFIRMATION_PHRASE})
                self.assertEqual(duplicate_gate.status_code, 409)
                self.assertEqual(queue.run_calls, total_before_duplicate)
            finally:
                restarted.stop()
                server2.shutdown()
                server2.server_close()
                thread2.join(timeout=5)

            final_restart = make_controller()
            final_state = final_restart.snapshot()
            self.assertEqual(final_state["state"], "PRESSURE_FINISHED")
            self.assertTrue(final_state["pressure_gate_accepted"])
            self.assertEqual(len(queue.executed_keys), 34)

            # Simulate a process ending after the explicit gate was persisted
            # but before its phase completion state reached disk.
            with final_restart._lock:
                final_restart._phase = "PRESSURE_RUNNING"
                final_restart._phase_states["pressure_batch_03"] = "RUNNING"
                final_restart._active_phase = "pressure_batch_03"
                final_restart._persist_state_locked()
            interrupted_restart = make_controller()
            interrupted_state = interrupted_restart.snapshot()
            self.assertEqual(interrupted_state["state"], "PRESSURE_INTERRUPTED_AWAITING_RESUME")
            self.assertTrue(interrupted_state["pressure_gate_accepted"])
            calls_before_resume = queue.run_calls
            self.assertTrue(interrupted_restart.start())
            interrupted_restart._worker.join(timeout=5)
            self.assertFalse(interrupted_restart._worker.is_alive())
            self.assertEqual(interrupted_restart.snapshot()["state"], "PRESSURE_FINISHED")
            self.assertEqual(queue.run_calls, calls_before_resume + 1)  # Drain check only; successes are not repeated.
            self.assertEqual(len(queue.executed_keys), 34)

    def test_canary_failure_keeps_pressure_gate_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = phase_plan(root)
            queue = PhaseTrackingQueue(root / "queue-state", plan)
            canary_ids = set(plan.cohorts["canary_A_and_B_union"])
            canary_rows = [row for row in plan.metadata["articles"] if row["article_id"] in canary_ids]
            for index, row in enumerate(canary_rows):
                item = queue.by_key[row["idempotency_key"]]
                item["status"] = "FAILED" if index == 0 else "SUCCEEDED"
            controller = app.AutomaticCanaryController(
                plan,
                queue=queue,
                activity_probe=lambda: (0, 0),
                model_ready_probe=lambda: True,
                api_key="unit-secret",
                transport_factory=lambda *_args: self.fail("pressure must not create a transport"),
            )
            with controller._lock:
                controller._phase = "CANARY_FAILED_WAITING_REVIEW"
                controller._phase_states["canary_A_and_B_union"] = "FAILED_WAITING_REVIEW"
                controller._persist_state_locked()
            self.assertFalse(controller.snapshot()["pressure_gate_available"])
            self.assertFalse(controller.authorize_pressure(app.PRESSURE_CONFIRMATION_PHRASE))
            state = controller.snapshot()
        self.assertFalse(state["pressure_gate_accepted"])
        self.assertEqual(state["phase_progress"]["canary_A_and_B_union"]["failed"], 1)
        self.assertEqual(state["phases"]["pressure_batch_03"], "NOT_STARTED")

    def test_pressure_gate_requires_measured_canary_wall_below_v5_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = phase_plan(root)
            queue = PhaseTrackingQueue(root / "queue-state", plan)
            canary_ids = set(plan.cohorts["canary_A_and_B_union"])
            for row in plan.metadata["articles"]:
                if row["article_id"] in canary_ids:
                    queue.by_key[row["idempotency_key"]]["status"] = "SUCCEEDED"
            controller = app.AutomaticCanaryController(
                plan,
                queue=queue,
                activity_probe=lambda: (0, 0),
                model_ready_probe=lambda: True,
                api_key="unit-secret",
                transport_factory=lambda *_args: self.fail("pressure must remain blocked"),
            )
            with controller._lock:
                controller._phase = "WAITING_QUALITY_REVIEW"
                controller._phase_states["canary_A_and_B_union"] = "WAITING_QUALITY_REVIEW"
                controller._phase_wall_seconds["canary_A_and_B_union"] = 184.730
                controller._persist_state_locked()
            self.assertTrue(controller.snapshot()["pressure_gate_available"])

            with controller._lock:
                controller._phase_wall_seconds["canary_A_and_B_union"] = app.CANARY_WALL_SPEED_LIMIT_SECONDS
                controller._persist_state_locked()
            state = controller.snapshot()
            self.assertFalse(state["pressure_gate_speed_ready"])
            self.assertFalse(state["pressure_gate_available"])
            self.assertFalse(controller.authorize_pressure(app.PRESSURE_CONFIRMATION_PHRASE))
            self.assertEqual(controller.snapshot()["stop_code"], "CANARY_WALL_TIME_NOT_BELOW_V5_REFERENCE")

    def test_canary_speed_total_adds_parser_preflight_once_to_execution_wall(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = phase_plan(root)
            queue = PhaseTrackingQueue(root / "queue-state", plan)
            canary_ids = set(plan.cohorts["canary_A_and_B_union"])
            for row in plan.metadata["articles"]:
                if row["article_id"] in canary_ids:
                    queue.by_key[row["idempotency_key"]]["status"] = "SUCCEEDED"
            controller = app.AutomaticCanaryController(
                plan,
                queue=queue,
                activity_probe=lambda: (0, 0),
                model_ready_probe=lambda: True,
                api_key="unit-secret",
                transport_factory=lambda *_args: self.fail("pressure must remain blocked"),
            )
            with controller._lock:
                controller._phase = "WAITING_QUALITY_REVIEW"
                controller._phase_states["canary_A_and_B_union"] = "WAITING_QUALITY_REVIEW"
                controller._phase_wall_seconds["canary_A_and_B_union"] = 184.730
                first_id = next(iter(plan.cohorts["canary_A_and_B_union"]))
                controller._fixed_fact_preflight_elapsed_by_article[first_id] = 0.002
                controller._canary_fixed_fact_preflight_seconds = 0.002
                controller._persist_state_locked()
            state = controller.snapshot()
        self.assertEqual(state["canary_execution_wall_seconds"], 184.730)
        self.assertEqual(state["canary_script_preflight_elapsed_seconds"], 0.002)
        self.assertEqual(state["canary_elapsed_seconds"], 184.732)
        self.assertFalse(state["pressure_gate_speed_ready"])
        self.assertFalse(state["pressure_gate_available"])

    def test_controller_uses_fresh_preflight_before_canary_and_restores_history_after_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            def make_plan(preflight_seconds: float) -> app.FrozenPlan:
                plan = phase_plan(root)
                canary_ids = set(plan.cohorts["canary_A_and_B_union"])
                plan.metadata["fixed_fact_extraction_elapsed_by_article"] = {
                    article_id: preflight_seconds for article_id in canary_ids
                }
                return plan

            def make_controller(plan: app.FrozenPlan) -> app.AutomaticCanaryController:
                return app.AutomaticCanaryController(
                    plan,
                    queue=PhaseTrackingQueue(root / "queue-state", plan),
                    activity_probe=lambda: (0, 0),
                    model_ready_probe=lambda: True,
                    api_key="unit-secret",
                    transport_factory=lambda *_args: self.fail("timing restore must not create a transport"),
                )

            stale_plan = make_plan(0.011)
            make_controller(stale_plan)  # Persist an older NOT_STARTED state for the same manifest.

            fresh_plan = make_plan(0.021)
            fresh_controller = make_controller(fresh_plan)
            self.assertEqual(fresh_controller._canary_fixed_fact_preflight_seconds, 0.126)
            self.assertEqual(
                fresh_controller._fixed_fact_preflight_elapsed_by_article,
                {article_id: 0.021 for article_id in fresh_plan.cohorts["canary_A_and_B_union"]},
            )

            with fresh_controller._lock:
                fresh_controller._phase = "WAITING_QUALITY_REVIEW"
                fresh_controller._phase_states["canary_A_and_B_union"] = "WAITING_QUALITY_REVIEW"
                fresh_controller._phase_wall_seconds["canary_A_and_B_union"] = 10.0
                fresh_controller._persist_state_locked()

            for restored_phase in ("WAITING_QUALITY_REVIEW", "CANARY_RUNNING"):
                with self.subTest(restored_phase=restored_phase):
                    if restored_phase == "CANARY_RUNNING":
                        with fresh_controller._lock:
                            fresh_controller._phase = "CANARY_RUNNING"
                            fresh_controller._phase_states["canary_A_and_B_union"] = "RUNNING"
                            fresh_controller._active_phase = "canary_A_and_B_union"
                            fresh_controller._persist_state_locked()
                    resumed = make_controller(make_plan(0.050))
                    resumed_state = resumed.snapshot()
                    self.assertEqual(resumed._canary_fixed_fact_preflight_seconds, 0.126)
                    self.assertEqual(resumed_state["canary_script_preflight_elapsed_seconds"], 0.126)
                    self.assertEqual(resumed_state["canary_execution_wall_seconds"], 10.0)
                    self.assertEqual(resumed_state["canary_elapsed_seconds"], 10.126)

    def test_mock_sse_is_streamed_with_finite_timeout_and_recorded_byte_for_byte(self) -> None:
        answer = sse([
            {"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}], "model": app.MODEL_ID},
            {"choices": [{"delta": {"content": "{\"ok\":"}, "finish_reason": None}], "model": app.MODEL_ID},
            {"choices": [{"delta": {"content": "true}"}, "finish_reason": "stop"}], "model": app.MODEL_ID},
            {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11}, "model": app.MODEL_ID},
        ], crlf=True)
        request_timeouts = []
        request_bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            request_timeouts.append(request.extensions["timeout"])
            request_bodies.append(json.loads(request.content))
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=answer)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = queue_module.QueueJob("a" * 64, "test-q", app.MODEL_ID, {}, {}, 1)
            transport = app.GatedStreamingTransport(
                "unit-secret", root, http_transport=httpx.MockTransport(handler)
            )
            transport.begin_job(job)
            clock = mock.Mock()
            clock.monotonic.side_effect = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75]
            with mock.patch.object(app, "time", clock), mock.patch.object(runner, "time", clock):
                result = transport.complete_batch([{"role": "user", "content": "fixture body"}])
            transport.finish_job(status="RESPONSE_RECEIVED", completion=result)
            trace = next((root / "streams").rglob("round-01.raw.sse"))
            receipt = json.loads(next((root / "streams").rglob("stream-receipt.json")).read_text())
            request_path = root / receipt["rounds"][0]["request_input_path"]
            request_raw = request_path.read_bytes()
            trace_bytes = trace.read_bytes()
            with self.assertRaisesRegex(ValueError, "IMMUTABLE_EVIDENCE_CONFLICT"):
                app._write_private_immutable(request_path, b"different request bytes")
            transport.close()
        self.assertEqual(result.final_text, "{\"ok\":true}")
        self.assertEqual(result.usage["completion_tokens"], 2)
        self.assertEqual(trace_bytes, answer)
        self.assertEqual(receipt["rounds"][0]["raw_sse_sha256"], sha(answer))
        self.assertEqual(json.loads(request_raw), request_bodies[0])
        self.assertEqual(receipt["rounds"][0]["request_input_sha256"], sha(request_raw))
        self.assertEqual(receipt["rounds"][0]["request_input_length_bytes"], len(request_raw))
        self.assertNotIn(b"unit-secret", request_raw)
        self.assertEqual(receipt["first_event_seconds"], 0.5)
        self.assertEqual(receipt["ttft_seconds"], receipt["first_event_seconds"])
        self.assertEqual(receipt["first_content_at"], "+0.750s")
        self.assertEqual(receipt["ttfc_seconds"], 0.75)
        self.assertGreater(receipt["ttfc_seconds"], receipt["ttft_seconds"])
        self.assertEqual(receipt["ttft_status"], "MEASURED")
        self.assertEqual(receipt["ttfc_status"], "MEASURED")
        self.assertEqual(request_timeouts[0]["read"], app.NO_PROGRESS_TIMEOUT_SECONDS)

    def test_structured_output_warning_fails_closed_before_consuming_sse(self) -> None:
        answer = sse([{"choices": [{"delta": {"content": "{}"}, "finish_reason": "stop"}], "model": app.MODEL_ID}])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = queue_module.QueueJob("b" * 64, "test-q", app.MODEL_ID, {}, {}, 1)
            transport = app.GatedStreamingTransport(
                "unit-secret",
                root,
                http_transport=httpx.MockTransport(
                    lambda _request: httpx.Response(
                        200,
                        headers={"content-type": "text/event-stream", "warning": '299 omlx "structured output unavailable"'},
                        content=answer,
                    )
                ),
            )
            transport.begin_job(job)
            contract = runner.load_active_contract()
            with self.assertRaisesRegex(runner.TransportError, "STRUCTURED_OUTPUT_HTTP_WARNING"):
                transport.complete_batch(
                    [{"role": "user", "content": "fixture body"}],
                    tools=[],
                    structured_outputs={"json": runner.build_simple_workflow_schema(contract)},
                    workflow_profile=runner.SIMPLE_WORKFLOW_PROFILE,
                )
            transport.finish_job(status="FAILED", code="STRUCTURED_OUTPUT_HTTP_WARNING")
            receipt = json.loads(next((root / "streams").rglob("stream-receipt.json")).read_text())
            transport.close()
        self.assertEqual(receipt["rounds"][0]["status"], "FAILED")
        self.assertEqual(receipt["rounds"][0]["raw_sse_length_bytes"], 0)
        self.assertEqual(receipt["rounds"][0]["structured_output_warning_headers"], ['299 omlx "structured output unavailable"'])

    def test_simple_workflow_fetch_requires_same_lookup_and_url_from_qualified_search(self) -> None:
        route_calls = []
        selected_url = "https://example.org/qualified"

        def handler(request: httpx.Request) -> httpx.Response:
            route_calls.append(request.url.path)
            if request.url.path == "/v1/web/search":
                return httpx.Response(200, json={"ok": True, "results": [{"title": "fixture", "url": selected_url}]})
            if request.url.path == "/v1/web/fetch":
                return httpx.Response(200, json={"ok": True, "content": "untrusted fixture"})
            return httpx.Response(404)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = queue_module.QueueJob("f" * 64, "test-q", app.MODEL_ID, {}, {}, 1)
            transport = app.GatedStreamingTransport("unit-secret", root, http_transport=httpx.MockTransport(handler))
            transport.begin_job(job)
            search, search_receipt = transport._call_simple_workflow_lookup({
                "operation": "search", "missing_fact": "filing date", "reader_field": "reason",
                "query": "issuer filing date", "url": "",
            }, lambda _event: None)
            fetched, fetch_receipt = transport._call_simple_workflow_lookup({
                "operation": "fetch", "missing_fact": "filing date", "reader_field": "reason",
                "query": "", "url": selected_url,
            }, lambda _event: None)
            self.assertTrue(search["ok"])
            self.assertTrue(fetched["ok"])
            self.assertEqual(search_receipt["workflow_operation"], "search")
            self.assertEqual(fetch_receipt["workflow_operation"], "fetch")
            transport.close()

        route_calls.clear()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = queue_module.QueueJob("a" * 64, "test-q", app.MODEL_ID, {}, {}, 1)
            transport = app.GatedStreamingTransport("unit-secret", root, http_transport=httpx.MockTransport(handler))
            transport.begin_job(job)
            transport._call_simple_workflow_lookup({
                "operation": "search", "missing_fact": "filing date", "reader_field": "reason",
                "query": "issuer filing date", "url": "",
            }, lambda _event: None)
            denied, denied_receipt = transport._call_simple_workflow_lookup({
                "operation": "fetch", "missing_fact": "filing date", "reader_field": "reason",
                "query": "", "url": "https://example.org/not-returned",
            }, lambda _event: None)
            transport.close()
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error"]["code"], "web_fetch_url_not_from_qualified_search")
        self.assertEqual(denied_receipt["workflow_operation"], "fetch")
        self.assertEqual(route_calls, ["/v1/web/search"])

    def test_executor_request_uses_one_structured_simple_reader_and_sends_the_full_body_once(self) -> None:
        body = "  frozen opening paragraph.\n\n| Field | Value |\n|---|---|\n| State | pending |\n\nExact ending.  "
        batch = fixtures.synthetic_batch(body)
        article = batch["articles"][0]
        batch_id = "AUTO_" + sha(article["article_id"].encode("utf-8"))[:20]
        contract = runner.load_active_contract()
        unit_map_for_ledger = runner.build_source_unit_map(article["article_body"], article["body_sha256"])
        ledger = runner.simple_fixed_facts.extract_fixed_facts(article["article_body"], unit_map_for_ledger, article["article_metadata"])
        article_with_ledger = {**article, "fixed_fact_ledger": ledger}
        frozen_batch = length_canary.make_batch([article_with_ledger], batch_id)
        expected_messages = runner.build_messages(frozen_batch, contract, runner.SIMPLE_WORKFLOW_PROFILE)
        expected_input_sha = runner._input_batch_sha(frozen_batch)
        expected_span_map = runner.build_source_span_map(article["article_body"], article["body_sha256"])
        expected_unit_map = runner.build_source_unit_map(article["article_body"], article["body_sha256"])
        wire_reader = fixtures.reader_output(article)
        wire_reader.update({"facts": [], "changes": [], "source_sha256": "", "body_sha256": ""})
        envelope = {"action": "complete", "lookup_request": None, "reader_output": wire_reader}
        answer_text = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        answer = sse([{"choices": [{"delta": {"content": answer_text}, "finish_reason": "stop"}], "model": app.MODEL_ID}])
        sent = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=answer)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            key = "e" * 64
            plan = app.FrozenPlan(
                records=(article,),
                cohorts={"canary_A_and_B_union": (article["article_id"],), "pressure_batch_03": ()},
                metadata={
                    "articles": [{
                        "article_id": article["article_id"],
                        "idempotency_key": key,
                        "input_sha256": expected_input_sha,
                        "source_span_map_sha256": expected_span_map["span_map_sha256"],
                        "source_unit_map_sha256": expected_unit_map["source_unit_map_sha256"],
                        "fixed_fact_parser_protocol": app.EXPECTED_FIXED_FACT_PARSER_PROTOCOL,
                        "fixed_fact_parser_sha256": app.EXPECTED_FIXED_FACT_PARSER_SHA256,
                        "fixed_fact_ledger_sha256": ledger["ledger_sha256"],
                        "script_fact_count": len(ledger["reader_facts"]) + len(ledger["reader_changes"]),
                        "script_fact_unknown_count": len(ledger["unknowns"]),
                    }],
                    "input_manifest_sha256": sha(b"manifest"),
                },
                manifest_path=root / "automatic-input-manifest.json",
            )
            payload = {
                **{name: article[name] for name in ("article_id", "source_sha256", "body_sha256", "article_body")},
                "article_metadata": article["article_metadata"],
                "fixed_fact_parser_protocol": app.EXPECTED_FIXED_FACT_PARSER_PROTOCOL,
                "fixed_fact_parser_sha256": app.EXPECTED_FIXED_FACT_PARSER_SHA256,
                "fixed_fact_ledger": ledger,
            }
            job = queue_module.QueueJob(key, "test-q", app.MODEL_ID, {}, payload, 1)
            controller = app.AutomaticCanaryController(
                plan,
                queue=EmptyQueue(root / "queue-state"),
                activity_probe=lambda: (0, 0),
                model_ready_probe=lambda: True,
                api_key="unit-secret",
            )
            transport = app.GatedStreamingTransport(
                "unit-secret", root, http_transport=httpx.MockTransport(handler)
            )
            raw = controller._execute(transport, job)
            receipt_path = next((root / "streams").rglob("stream-receipt.json"))
            receipt_raw = receipt_path.read_bytes()
            stream_receipt = json.loads(receipt_raw)
            request_input_path = root / stream_receipt["rounds"][0]["request_input_path"]
            request_input_raw = request_input_path.read_bytes()
            transport.close()
        self.assertEqual(raw, answer_text)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["messages"], expected_messages)
        self.assertEqual(json.loads(request_input_raw), sent[0])
        self.assertEqual(stream_receipt["rounds"][0]["request_input_sha256"], sha(request_input_raw))
        self.assertEqual(stream_receipt["rounds"][0]["request_input_length_bytes"], len(request_input_raw))
        self.assertEqual(sha(sent[0]["messages"][0]["content"].encode("utf-8")), app.EXPECTED_SYSTEM_PROMPT_SHA256)
        system_prompt = sent[0]["messages"][0]["content"]
        self.assertEqual(system_prompt.count("JSON_SCHEMA_BEGIN"), 1)
        self.assertIn("SIMPLE_WORKFLOW_JSON_SCHEMA_BEGIN", system_prompt)
        self.assertNotIn("ACTIVE_READER_JSON_SCHEMA_BEGIN", system_prompt)
        self.assertNotIn("SOURCE_RANGE_SINGLE_WIRE_JSON_SCHEMA_BEGIN", system_prompt)
        embedded = json.loads(sent[0]["messages"][1]["content"].removeprefix("ARTICLE_DATA_BEGIN\n").removesuffix("\nARTICLE_DATA_END"))
        model_article = embedded["article"]
        self.assertNotIn("article_body", model_article)
        self.assertEqual("".join(unit["text"] for unit in model_article["source_units"]), article["article_body"])
        self.assertTrue(any("| Field | Value |" in unit["text"] for unit in model_article["source_units"]))
        self.assertTrue(all(set(unit) == {"source_unit_id", "text"} for unit in model_article["source_units"]))
        self.assertEqual(set(model_article["article_metadata"]), {"publication_date", "observed_at", "available_at", "pit_status"})
        self.assertNotIn(article["article_id"], sent[0]["messages"][1]["content"])
        self.assertNotIn("source_unit_map_sha256", sent[0]["messages"][1]["content"])
        self.assertNotIn("start_cp", sent[0]["messages"][1]["content"])
        self.assertEqual(sent[0]["model"], "qwen3_8_flash_next")
        self.assertNotIn("tools", sent[0])
        self.assertNotIn("response_format", sent[0])
        self.assertEqual(sent[0]["structured_outputs"], {"json": runner.build_simple_workflow_schema(contract)})
        self.assertEqual(sent[0]["max_tokens"], app.MAX_COMPLETION_TOKENS)
        self.assertEqual(sent[0]["temperature"], 0.0)
        self.assertIs(sent[0]["enable_thinking"], False)
        self.assertNotIn("thinking_budget", sent[0])
        self.assertNotIn(b"unit-secret", receipt_raw)

    def test_temperature_override_is_simple_profile_scoped_and_legacy_request_is_unchanged(self) -> None:
        answer = sse([{
            "choices": [{"delta": {"content": "{\"ok\":true}"}, "finish_reason": "stop"}],
            "model": app.MODEL_ID,
        }])
        sent = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=answer)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transport = app.GatedStreamingTransport(
                "unit-secret", root, http_transport=httpx.MockTransport(handler)
            )
            for attempt, profile in enumerate(
                (runner.SIMPLE_WORKFLOW_PROFILE, app.PREVIOUS_PROFILE), start=1
            ):
                job = queue_module.QueueJob(
                    chr(ord("a") + attempt) * 64, "test-q", app.MODEL_ID, {}, {}, attempt
                )
                transport.begin_job(job)
                structured_outputs = {"json": {"type": "object"}} if profile == runner.SIMPLE_WORKFLOW_PROFILE else None
                transport._stream_completion(
                    [{"role": "user", "content": "frozen fixture"}],
                    lambda _event: None,
                    tools=[],
                    structured_outputs=structured_outputs,
                    workflow_profile=profile,
                )
                transport.finish_job(status="RESPONSE_RECEIVED")
            transport.close()

        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0]["temperature"], 0.0)
        self.assertNotIn("temperature", sent[1])
        self.assertEqual(sent[0]["enable_thinking"], False)
        self.assertEqual(sent[1]["enable_thinking"], False)

    def test_raw_wire_is_persisted_before_unit_projection_and_final_reader_validation(self) -> None:
        body = "  公司披露：回购价格为 10.00 元；正文没有市场比较。\r\n"
        batch = fixtures.synthetic_batch(body)
        article = batch["articles"][0]
        batch_id = "AUTO_" + sha(article["article_id"].encode("utf-8"))[:20]
        frozen_batch = length_canary.make_batch([article], batch_id)
        span_map = runner.build_source_span_map(body, article["body_sha256"])
        unit_map = runner.build_source_unit_map(body, article["body_sha256"])
        ledger = runner._simple_fixed_fact_ledger(article, unit_map)
        selected_unit = unit_map["units"][0]
        reader = fixtures.reader_output(article)
        reader["reason"] = "Keep this conclusion byte-for-byte."
        reader["risk_notes"] = ["PIT status remains as supplied."]
        original_model_risk_notes = list(reader["risk_notes"])
        # This intentionally overclaims what the authentic quote supports. The
        # projection proves exact quote provenance; the independent quality gate
        # remains required to assess claim support.
        overclaim = "Revenue rose and the price is historically low."
        for field_name in runner.SOURCE_SPAN_CITATION_FIELDS:
            reader[field_name] = [{"claim": overclaim, "source_unit_id": selected_unit["source_unit_id"]}]
        wire = {"action": "complete", "lookup_request": None, "reader_output": reader}
        raw_wire = json.dumps(wire, ensure_ascii=False, separators=(",", ":"))

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            queue_id = "simple-workflow-unit-test"
            queue = queue_module.SerialAnnouncementQueue(
                root / "queue-state" / queue_id,
                queue_id,
                app.MODEL_ID,
                max_attempts=1,
            )
            payload = queue_payload()
            payload.update({
                **{name: article[name] for name in ("article_id", "source_sha256", "body_sha256", "article_body")},
                "article_metadata": article["article_metadata"],
                "fixed_fact_parser_sha256": app.EXPECTED_FIXED_FACT_PARSER_SHA256,
                "fixed_fact_ledger": ledger,
            })
            payload["rules"] = (
                f"{app.ARTICLE_RULES}+source-span-map:{span_map['span_map_sha256']}"
                f"+source-unit-map:{unit_map['source_unit_map_sha256']}"
            )
            payload["source_span_map_sha256"] = span_map["span_map_sha256"]
            payload["source_unit_map_sha256"] = unit_map["source_unit_map_sha256"]
            queued = queue.enqueue(payload)
            row = {
                "article_id": article["article_id"],
                "idempotency_key": queued["idempotency_key"],
                "input_sha256": runner._input_batch_sha(frozen_batch),
                "source_span_map_sha256": span_map["span_map_sha256"],
                "source_unit_map_sha256": unit_map["source_unit_map_sha256"],
                "fixed_fact_parser_sha256": app.EXPECTED_FIXED_FACT_PARSER_SHA256,
                "fixed_fact_ledger_sha256": ledger["ledger_sha256"],
                "context_admission": "READY",
            }
            plan = app.FrozenPlan(
                records=(article,),
                cohorts={"canary_A_and_B_union": (article["article_id"],), "pressure_batch_03": ()},
                metadata={"articles": [row], "input_manifest_sha256": sha(b"manifest"), "queue_id": queue_id},
                manifest_path=root / "automatic-input-manifest.json",
            )
            gold = {
                "schema": "qwen_flash_next.simple_workflow_fixed_gold.v1",
                "provided_to_model": False,
                "articles": {
                    article["article_id"]: {
                        "identities": {
                            "source_sha256": article["source_sha256"],
                            "body_sha256": article["body_sha256"],
                            "source_unit_map_sha256": unit_map["source_unit_map_sha256"],
                            "fixed_fact_ledger_sha256": ledger["ledger_sha256"],
                        },
                        "classification": {
                            "disposition": "NOT_SELECTED",
                            "selection_basis": "NOT_SELECTED",
                            "direction": "NEUTRAL",
                            "evidence_sufficiency": "VERIFIED_EXISTING_FACTS",
                        },
                        "pit_provenance": {
                            "pit_status": "CANNOT_CONFIRM",
                            "pit_reason_status": "NOT_PROVIDED",
                            "pit_reason": None,
                        },
                    }
                },
            }
            gold_raw = json.dumps(gold, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
            (root / "fixed-gold-regression.json").write_bytes(gold_raw)
            controller = app.AutomaticCanaryController(
                plan,
                queue=queue,
                activity_probe=lambda: (0, 0),
                model_ready_probe=lambda: True,
                api_key="unit-secret",
            )
            result = queue.run_next(lambda _job: raw_wire, controller._validate, wait_for_model_slot=False)
            self.assertEqual(result["status"], "SUCCEEDED", result)
            item = next(value for value in queue.snapshot()["items"] if value["idempotency_key"] == queued["idempotency_key"])
            raw_path = Path(item["raw_path"])
            validated_path = Path(item["validated_path"])
            receipt_path = root / "projection-receipts" / f"{queued['idempotency_key']}-attempt-0001.json"
            raw_saved = raw_path.read_bytes()
            validated = json.loads(validated_path.read_bytes())
            receipt = json.loads(receipt_path.read_bytes())

        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(raw_saved, raw_wire.encode("utf-8"))
        self.assertEqual(item["raw_sha256"], sha(raw_saved))
        self.assertEqual(receipt["raw_wire_sha256"], sha(raw_saved))
        self.assertEqual(receipt["raw_wire_artifact"], str(raw_path.relative_to(queue.state_root)))
        self.assertEqual(receipt["semantic_quality"], "NOT_ASSESSED_BY_AUTOMATION")
        self.assertEqual(receipt["gold_regression"]["status"], "FAIL")
        self.assertEqual(receipt["gold_regression"]["evaluation_kind"], "DETERMINISTIC_FIXED_GOLD_REGRESSION_ONLY")
        self.assertEqual(receipt["gold_regression"]["semantic_quality"], "NOT_ASSESSED_BY_AUTOMATION")
        self.assertFalse(receipt["gold_regression"]["reader_output_modified"])
        self.assertEqual(receipt["gold_regression"]["gold_sha256"], sha(gold_raw))
        self.assertEqual(receipt["gold_regression"]["checks"]["classification"]["status"], "FAIL")
        self.assertEqual(receipt["gold_regression"]["checks"]["pit_provenance"]["status"], "PASS")
        self.assertEqual(receipt["gold_regression"]["checks"]["fixed_ledger_identity"]["status"], "PASS")
        self.assertEqual(receipt["gold_regression"]["checks"]["references"]["status"], "PASS")
        self.assertEqual(receipt["schema"], "qwen_flash_next.simple_workflow_projection_receipt.v1")
        self.assertEqual(receipt["protocol"], runner.SIMPLE_WORKFLOW_PROTOCOL)
        self.assertEqual(receipt["final_projection_sha256"], sha(runner.canonical_json_bytes(validated)))
        self.assertEqual(receipt["final_projection_artifact"], str(validated_path.relative_to(queue.state_root)))
        self.assertNotIn("article_body", json.dumps(receipt, ensure_ascii=False))
        projected = validated["reader_output"]
        self.assertEqual(set(projected), set(runner.load_active_contract().reader_schema["properties"]))
        for field_name in ("disposition", "selection_basis", "direction", "evidence_sufficiency"):
            self.assertEqual(projected[field_name], reader[field_name], field_name)
        self.assertEqual(projected["reason"], reader["reason"])
        pit_provenance = receipt["simple_workflow_projection"]["program_input_pit_provenance"]
        self.assertEqual(reader["risk_notes"], original_model_risk_notes)
        self.assertEqual(projected["risk_notes"][:-1], original_model_risk_notes)
        self.assertEqual(projected["risk_notes"][-1], pit_provenance["annotation"])
        self.assertEqual(
            receipt["simple_workflow_projection"]["model_risk_notes_before_projection"]["count"],
            len(original_model_risk_notes),
        )
        for field_name in set(runner.SOURCE_SPAN_CITATION_FIELDS) - {"facts", "changes"}:
            citation = projected[field_name][0]
            self.assertEqual(citation["claim"], overclaim)
            self.assertEqual(citation["quote"], body[selected_unit["start_cp"]:selected_unit["end_cp"]])
        units_by_id = {unit["source_unit_id"]: unit for unit in unit_map["units"]}
        for field_name, ledger_field in (("facts", "reader_facts"), ("changes", "reader_changes")):
            self.assertEqual(
                [item["claim"] for item in projected[field_name]],
                [item["claim"] for item in ledger[ledger_field]],
            )
            for item, source in zip(projected[field_name], ledger[ledger_field], strict=True):
                unit = units_by_id[source["source_unit_id"]]
                self.assertEqual(item["quote"], unit["text"])
                self.assertEqual(item["locator"], f"article_body[codepoint:{unit['start_cp']}:{unit['end_cp']}]")
        self.assertEqual(projected["reason"], reader["reason"])
        self.assertEqual(projected["risk_notes"][:-1], original_model_risk_notes)

    def test_simple_workflow_gold_diff_never_rewrites_a_mismatching_classification(self) -> None:
        reader = {
            "disposition": "NOT_ASSESSED",
            "selection_basis": "NOT_ASSESSED",
            "direction": "UNKNOWN",
            "evidence_sufficiency": "INSUFFICIENT_EXISTING_FACTS",
            "risk_notes": ["model note", "program PIT annotation"],
        }
        before = json.loads(json.dumps(reader))
        expected = {
            "classification": {
                "disposition": "NOT_SELECTED",
                "selection_basis": "NOT_SELECTED",
                "direction": "NEUTRAL",
                "evidence_sufficiency": "VERIFIED_EXISTING_FACTS",
            },
            "identities": {
                "source_sha256": "a" * 64,
                "body_sha256": "b" * 64,
                "source_unit_map_sha256": "c" * 64,
                "fixed_fact_ledger_sha256": "d" * 64,
            },
            "pit_provenance": {
                "pit_status": "CANNOT_CONFIRM",
                "pit_reason_status": "NOT_PROVIDED",
                "pit_reason": None,
            },
        }
        projection = {
            **expected["identities"],
            "model_risk_notes_before_projection": {
                "count": 1,
                "sha256": sha(runner.canonical_json_bytes(["model note"])),
            },
            "program_input_pit_provenance": {
                **expected["pit_provenance"],
                "annotation": "program PIT annotation",
            },
            "citation_projections": [],
        }
        receipt = app._simple_workflow_gold_diff_receipt(
            expected, reader, projection, references_validated=True
        )
        self.assertEqual(receipt["status"], "FAIL")
        self.assertEqual(receipt["checks"]["classification"]["status"], "FAIL")
        self.assertEqual(receipt["checks"]["pit_provenance"]["status"], "PASS")
        self.assertEqual(receipt["checks"]["fixed_ledger_identity"]["status"], "PASS")
        self.assertEqual(receipt["checks"]["references"]["status"], "PASS")
        self.assertEqual(reader, before)

    def test_timeout_retains_partial_sse_and_failure_receipt(self) -> None:
        partial = b'data: {"choices":[{"delta":{"content":"partial"'

        class Interrupted(httpx.SyncByteStream):
            def __iter__(self):
                yield partial
                raise httpx.ReadTimeout("fixture timeout")

            def close(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = queue_module.QueueJob("b" * 64, "test-q", app.MODEL_ID, {}, {}, 1)
            transport = app.GatedStreamingTransport(
                "unit-secret",
                root,
                http_transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=Interrupted())),
            )
            transport.begin_job(job)
            with self.assertRaises(runner.TransportError) as caught:
                transport.complete_batch([{"role": "user", "content": "fixture"}])
            transport.finish_job(status="FAILED", code=str(caught.exception).split(":", 1)[0])
            trace = next((root / "streams").rglob("round-01.raw.sse"))
            receipt = json.loads(next((root / "streams").rglob("stream-receipt.json")).read_text())
            trace_bytes = trace.read_bytes()
            transport.close()
        self.assertIn("CHAT_NO_PROGRESS_TIMEOUT", str(caught.exception))
        self.assertEqual(trace_bytes, partial)
        self.assertEqual(receipt["rounds"][0]["raw_sse_sha256"], sha(partial))
        self.assertEqual(receipt["rounds"][0]["status"], "FAILED")

    def test_missing_web_contract_is_denied_and_model_can_continue(self) -> None:
        first = sse([{
            "choices": [{
                "delta": {"tool_calls": [{
                    "index": 0,
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": json.dumps({"query": "generic market performance"})},
                }]},
                "finish_reason": "tool_calls",
            }],
            "model": app.MODEL_ID,
        }])
        final = sse([{"choices": [{"delta": {"content": "{\"answer\":\"based on supplied body\"}"}, "finish_reason": "stop"}], "model": app.MODEL_ID}])
        completion_requests = []
        web_requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/chat/completions":
                completion_requests.append(json.loads(request.content))
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=first if len(completion_requests) == 1 else final)
            web_requests.append(request)
            return httpx.Response(200, json={"ok": True, "results": []})

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = queue_module.QueueJob("c" * 64, "test-q", app.MODEL_ID, {}, {}, 1)
            transport = app.GatedStreamingTransport("unit-secret", root, http_transport=httpx.MockTransport(handler))
            transport.begin_job(job)
            result = transport.complete_batch([{"role": "user", "content": "complete supplied body fact"}])
            receipt = result.tool_receipts[0]
            transport.close()
        self.assertEqual(result.final_text, "{\"answer\":\"based on supplied body\"}")
        self.assertEqual(len(completion_requests), 2)
        self.assertEqual(web_requests, [])
        self.assertEqual(receipt["status"], "failed")
        self.assertIsNone(receipt["input_sha256"])
        self.assertIn("web_lookup_contract_missing", completion_requests[1]["messages"][-1]["content"])
        self.assertIn("complete supplied body fact", completion_requests[1]["messages"][0]["content"])

    def test_one_web_failure_is_saved_and_repeated_lookup_is_suppressed(self) -> None:
        route_calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            route_calls.append(request)
            return httpx.Response(503, content=b"upstream fixture failure")

        properties = runner.load_active_contract().reader_schema["properties"]
        field = next(iter(properties))
        query1 = f"MISSING_FACT: filing date\nREADER_FIELD: {field}\nQUERY: issuer filing date"
        query2 = f"MISSING_FACT: exchange date\nREADER_FIELD: {field}\nQUERY: exchange publication date"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = queue_module.QueueJob("d" * 64, "test-q", app.MODEL_ID, {}, {}, 1)
            transport = app.GatedStreamingTransport("unit-secret", root, http_transport=httpx.MockTransport(handler))
            transport.begin_job(job)
            first, first_receipt = transport._call_web_tool("web_search", {"query": query1}, lambda _e: None)
            second, second_receipt = transport._call_web_tool("web_search", {"query": query2}, lambda _e: None)
            raw_path = root / first_receipt["raw_source_path"]
            raw = raw_path.read_bytes()
            transport.close()
        self.assertFalse(first["ok"])
        self.assertFalse(second["ok"])
        self.assertEqual(len(route_calls), 1)
        self.assertEqual(second_receipt["input_sha256"], None)
        self.assertEqual(raw, b"upstream fixture failure")
        self.assertEqual(first_receipt["raw_source_sha256"], sha(raw))

    def test_simple_lookup_cached_search_restores_only_its_own_fetch_urls(self) -> None:
        route_calls = []
        first_url = "https://example.org/first"
        second_url = "https://example.org/second"

        def handler(request: httpx.Request) -> httpx.Response:
            route_calls.append((request.url.path, json.loads(request.content)))
            if request.url.path == "/v1/web/search":
                query = json.loads(request.content)["query"]
                result_url = first_url if query == "focused first query" else second_url
                return httpx.Response(200, json={"ok": True, "results": [{"url": result_url}]})
            if request.url.path == "/v1/web/fetch":
                return httpx.Response(200, json={"ok": True, "content": "fetched fixture"})
            self.fail(f"unexpected local web route {request.url.path}")

        def search(query: str) -> dict[str, Any]:
            return {
                "operation": "search",
                "missing_fact": "a specific absent fact",
                "reader_field": "reason",
                "query": query,
                "url": "",
            }

        def fetch(url: str) -> dict[str, Any]:
            return {
                "operation": "fetch",
                "missing_fact": "a specific absent fact",
                "reader_field": "reason",
                "query": "",
                "url": url,
            }

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = queue_module.QueueJob("e" * 64, "test-q", app.MODEL_ID, {}, {}, 1)
            transport = app.GatedStreamingTransport(
                "unit-secret", root, http_transport=httpx.MockTransport(handler)
            )
            transport.begin_job(job)
            first, first_receipt = transport._call_simple_workflow_lookup(search("focused first query"), lambda _e: None)
            cached, cached_receipt = transport._call_simple_workflow_lookup(search("focused first query"), lambda _e: None)
            fetched, fetch_receipt = transport._call_simple_workflow_lookup(fetch(first_url), lambda _e: None)
            other_search, _ = transport._call_simple_workflow_lookup(search("focused second query"), lambda _e: None)
            rejected, rejected_receipt = transport._call_simple_workflow_lookup(fetch(first_url), lambda _e: None)
            transport.finish_job(status="TEST_COMPLETE")
            transport.close()

        self.assertTrue(first["ok"])
        self.assertFalse(first_receipt["reused_cached_result"])
        self.assertTrue(cached["ok"])
        self.assertTrue(cached_receipt["reused_cached_result"])
        self.assertTrue(fetched["ok"])
        self.assertEqual(fetch_receipt["status"], "ok")
        self.assertTrue(other_search["ok"])
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected_receipt["status"], "failed")
        self.assertEqual(rejected["error"]["code"], "web_fetch_url_not_from_qualified_search")
        self.assertEqual([path for path, _ in route_calls], [
            "/v1/web/search", "/v1/web/fetch", "/v1/web/search",
        ])

    def test_empty_or_context_failure_raw_is_saved_by_existing_queue(self) -> None:
        for executor_result, expected_code in ((b"", None), (queue_module.ExecutorFailure("CONTEXT_ITEM_UNFIT", code="CONTEXT_ITEM_UNFIT", raw_response=b""), "CONTEXT_ITEM_UNFIT")):
            with self.subTest(expected_code=expected_code), tempfile.TemporaryDirectory() as temp:
                queue = queue_module.SerialAnnouncementQueue(Path(temp), "test-q", app.MODEL_ID, max_attempts=1)
                queued = queue.enqueue(queue_payload())

                def execute(_job):
                    if isinstance(executor_result, Exception):
                        raise executor_result
                    return executor_result

                result = queue.run_next(execute, lambda _job, parsed: parsed, wait_for_model_slot=False)
                item = next(row for row in queue.snapshot()["items"] if row["idempotency_key"] == queued["idempotency_key"])
                raw_path = Path(item["raw_path"])
                self.assertTrue(raw_path.is_file())
                self.assertEqual(raw_path.read_bytes(), b"")
                self.assertEqual(item["raw_sha256"], sha(b""))
                if expected_code:
                    self.assertEqual((result.get("last_error") or {}).get("code"), expected_code)

    def test_visible_start_is_required_and_duplicate_start_does_not_duplicate_work(self) -> None:
        secret = "unit-secret-must-not-be-rendered"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = fake_plan(root, article_count=1)
            article = plan.records[0]
            key = plan.metadata["articles"][0]["idempotency_key"]
            item = {"article_id": article["article_id"], "idempotency_key": key, "status": "PENDING", "attempt_count": 0, "max_attempts": 2}
            queue = EmptyQueue(root / "queue-state", [item])
            calls = {"activity": 0, "model_ready": 0, "transport_factory": 0}

            def activity():
                calls["activity"] += 1
                return 0, 0

            def model_ready():
                calls["model_ready"] += 1
                return True

            class MockTransport:
                def __init__(self):
                    pass

                def close(self):
                    return None

            def transport_factory(_key, _root):
                calls["transport_factory"] += 1
                return MockTransport()

            controller = app.AutomaticCanaryController(
                plan,
                queue=queue,
                activity_probe=activity,
                model_ready_probe=model_ready,
                api_key=secret,
                transport_factory=transport_factory,
            )
            server = app.create_server(controller)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            client = httpx.Client(trust_env=False)
            try:
                url = f"http://127.0.0.1:{server.server_address[1]}"
                page = client.get(url + "/").text
                self.assertNotIn(secret, page)
                self.assertEqual(calls["transport_factory"], 0)
                self.assertEqual(queue.run_calls, 0)
                missing_csrf = client.post(url + "/api/start", json={})
                self.assertEqual(missing_csrf.status_code, 403)
                headers = {
                    "Origin": url,
                    "X-Canary-CSRF": server.canary_csrf_token,
                }
                accepted = client.post(url + "/api/start", json={}, headers=headers)
                self.assertEqual(accepted.status_code, 202)
                worker = controller._worker
                self.assertIsNotNone(worker)
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                duplicate = client.post(url + "/api/start", json={}, headers=headers)
                self.assertEqual(duplicate.status_code, 409)
            finally:
                controller.stop()
                server.shutdown()
                server.server_close()
                client.close()
                thread.join(timeout=5)
            self.assertEqual(calls["transport_factory"], 1)
            self.assertEqual(calls["activity"], 2)
            self.assertEqual(calls["model_ready"], 1)
            self.assertEqual(queue.run_calls, 1)

    def test_failed_request_stops_when_admin_activity_cannot_be_proven_idle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = fake_plan(root, article_count=2)
            keys = [row["idempotency_key"] for row in plan.metadata["articles"]]
            items = [
                {"article_id": plan.metadata["articles"][0]["article_id"], "idempotency_key": keys[0], "status": "FAILED", "attempt_count": 1, "max_attempts": 2, "last_error": {"code": "CHAT_NO_PROGRESS_TIMEOUT"}},
                {"article_id": plan.metadata["articles"][1]["article_id"], "idempotency_key": keys[1], "status": "PENDING", "attempt_count": 0, "max_attempts": 2, "last_error": None},
            ]
            queue = EmptyQueue(root / "queue-state", items, results=[{
                "status": "FAILED",
                "idempotency_key": keys[0],
                "attempt_count": 1,
                "last_error": {"code": "CHAT_NO_PROGRESS_TIMEOUT"},
                "raw_sha256": sha(b"partial stream"),
                "validated_sha256": None,
                "attempts": [{"duration_seconds": 0.75}, {"duration_seconds": 1.25}],
            }])
            activity_values = iter([(0, 0), (0, 0), (1, 0)])

            class MockTransport:
                def close(self):
                    return None

            controller = app.AutomaticCanaryController(
                plan,
                queue=queue,
                activity_probe=lambda: next(activity_values),
                model_ready_probe=lambda: True,
                api_key="unit-secret",
                transport_factory=lambda *_args: MockTransport(),
                idle_timeout_seconds=0,
            )
            self.assertTrue(controller.start())
            controller._worker.join(timeout=5)
            self.assertFalse(controller._worker.is_alive())
            state = controller.snapshot()
            receipt = json.loads((root / "automatic-run-receipt.json").read_text())
        self.assertEqual(queue.run_calls, 1)
        self.assertEqual(state["state"], "PAUSED_ACTIVITY_UNVERIFIED")
        self.assertEqual(state["stop_code"], "EXTERNAL_OR_STUCK_ACTIVITY_PRESENT")
        self.assertEqual(state["queue_status_counts"]["PENDING"], 1)
        self.assertEqual(receipt["scheduled_unique_count"], 2)
        self.assertEqual(receipt["semantic_quality"], "NOT_ASSESSED_BY_AUTOMATION")
        self.assertEqual(receipt["wall_seconds_all_attempts"], 2.0)


if __name__ == "__main__":
    unittest.main()
