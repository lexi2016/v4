from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from announcement_queue import (
    ExecutorFailure,
    SerialAnnouncementQueue,
    ValidationRejected,
)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def payload(article_id: str, body: str | None = None, **overrides: object) -> dict[str, object]:
    body_value = body if body is not None else f"body:{article_id}"
    value: dict[str, object] = {
        "date": "2026-10-14",
        "market": "HK",
        "article_id": article_id,
        "source_sha256": sha(f"source:{article_id}"),
        "body_sha256": sha(body_value),
        "prompt_sha256": "a" * 64,
        "model_id": "qwen3_8_flash_next",
        "configuration_sha256": "b" * 64,
        "rules": {"version": "frozen-test-rules"},
        "role": "reader",
        "stage": "announcement",
        "article_body": body_value,
    }
    value.update(overrides)
    return value


def json_executor(job: object) -> str:
    article_id = job.payload["article_id"]  # type: ignore[attr-defined]
    return json.dumps({"article_id": article_id, "accepted": True})


def pass_validator(job: object, parsed: object) -> object:
    expected_id = job.payload["article_id"]  # type: ignore[attr-defined]
    if not isinstance(parsed, dict) or parsed.get("article_id") != expected_id:
        raise ValidationRejected("article identity mismatch", code="ARTICLE_ID_MISMATCH")
    return parsed


class AnnouncementQueueTests(unittest.TestCase):
    def test_length_order_keeps_full_oversize_body_and_conserves_status_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            queue = SerialAnnouncementQueue(temp, "announcements", "qwen3_8_flash_next", max_attempts=2, max_body_bytes=12)
            long_body = "full body must stay intact"
            inputs = [
                payload("article-long", long_body),
                payload("article-medium", "middle"),
                payload("article-short", "x"),
                payload("article-missing", "raw body", body_sha256=None),
                payload("article-missing", "different raw body", body_sha256=None),
            ]
            queue.enqueue_many(inputs)
            initial = queue.snapshot()
            self.assertEqual(initial["total"], 5)
            self.assertEqual(sum(initial["status_counts"].values()), 5)
            self.assertTrue(initial["conservation_ok"])
            self.assertEqual(initial["status_counts"]["OVERSIZE"], 1)
            self.assertEqual(initial["status_counts"]["MISSING_MATERIAL"], 2)
            self.assertEqual(initial["unassessed_count"], 2)
            self.assertEqual(initial["not_selected_count"], 0)

            oversize = next(item for item in initial["items"] if item["identity"]["article_id"] == "article-long")
            saved_input = json.loads((Path(temp) / "jobs" / oversize["idempotency_key"] / "input.json").read_text())
            self.assertEqual(saved_input["article_body"], long_body)
            self.assertEqual(oversize["status"], "OVERSIZE")
            self.assertEqual((Path(temp) / "jobs").stat().st_mode & 0o777, 0o700)
            self.assertEqual((Path(temp) / "jobs" / oversize["idempotency_key"]).stat().st_mode & 0o777, 0o700)
            self.assertEqual((Path(temp) / "jobs" / oversize["idempotency_key"] / "input.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual((Path(temp) / "queue-state.json").stat().st_mode & 0o777, 0o600)

            submitted: list[str] = []

            def executor(job: object) -> str:
                submitted.append(job.payload["article_id"])  # type: ignore[attr-defined]
                return json_executor(job)

            outcomes = queue.run_pending(executor, pass_validator)
            self.assertEqual([result["status"] for result in outcomes], ["SUCCEEDED", "SUCCEEDED"])
            self.assertEqual(submitted, ["article-short", "article-medium"])
            final = queue.snapshot()
            self.assertEqual(final["status_counts"]["SUCCEEDED"], 2)
            self.assertEqual(final["status_counts"]["OVERSIZE"], 1)
            self.assertEqual(final["status_counts"]["MISSING_MATERIAL"], 2)
            self.assertEqual(sum(final["status_counts"].values()), final["total"])

    def test_raw_is_durable_before_validator_and_failures_do_not_block_following_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            queue = SerialAnnouncementQueue(temp, "announcements", "qwen3_8_flash_next", max_attempts=2)
            for article_id, size in (("timeout", 1), ("transport", 2), ("invalid-json", 3), ("quote", 4), ("success", 5)):
                queue.enqueue(payload(article_id, "x" * size))
            observed_raw_before_validation: list[str] = []

            def executor(job: object) -> str | bytes:
                article_id = job.payload["article_id"]  # type: ignore[attr-defined]
                if article_id == "timeout":
                    raise TimeoutError("simulated transport deadline")
                if article_id == "transport":
                    raise ExecutorFailure(
                        "connection ended after response bytes arrived",
                        code="TRANSPORT_ERROR",
                        raw_response=b'{"partial":',
                    )
                if article_id == "invalid-json":
                    return "{not-json"
                return json.dumps({"article_id": article_id, "accepted": True})

            def validator(job: object, parsed: object) -> object:
                article_id = job.payload["article_id"]  # type: ignore[attr-defined]
                if article_id == "quote":
                    item = next(
                        item for item in queue.snapshot()["items"]
                        if item["idempotency_key"] == job.idempotency_key  # type: ignore[attr-defined]
                    )
                    self.assertIsNotNone(item["raw_path"])
                    raw_path = Path(item["raw_path"])
                    self.assertTrue(raw_path.is_file())
                    observed_raw_before_validation.append(raw_path.read_text(encoding="utf-8"))
                    raise ValidationRejected("exact source quote rejected", code="QUOTE_MISMATCH")
                return pass_validator(job, parsed)

            outcomes = queue.run_pending(executor, validator)
            self.assertEqual(len(outcomes), 5)
            self.assertEqual(observed_raw_before_validation, ['{"article_id": "quote", "accepted": true}'])
            by_id = {item["identity"]["article_id"]: item for item in queue.snapshot()["items"]}
            self.assertEqual(by_id["timeout"]["last_error"]["code"], "TIMEOUT")
            self.assertEqual(by_id["transport"]["last_error"]["code"], "TRANSPORT_ERROR")
            self.assertEqual(by_id["invalid-json"]["last_error"]["code"], "INVALID_JSON")
            self.assertEqual(by_id["quote"]["last_error"]["code"], "QUOTE_MISMATCH")
            self.assertEqual(by_id["success"]["status"], "SUCCEEDED")
            quote_attempt = by_id["quote"]["attempts"][0]
            self.assertEqual(quote_attempt["status"], "FAILED")
            self.assertGreaterEqual(quote_attempt["duration_seconds"], 0)
            self.assertEqual(quote_attempt["error"]["code"], "QUOTE_MISMATCH")
            for article_id in ("transport", "invalid-json", "quote"):
                item = by_id[article_id]
                raw_path = Path(item["raw_path"])
                raw_bytes = raw_path.read_bytes()
                self.assertEqual(hashlib.sha256(raw_bytes).hexdigest(), item["raw_sha256"])
                self.assertEqual(raw_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(by_id["transport"]["raw_sha256"], hashlib.sha256(b'{"partial":').hexdigest())
            events = queue.snapshot()["recent_events"]
            quote_events = [event["event"] for event in events if event["idempotency_key"] == by_id["quote"]["idempotency_key"]]
            self.assertLess(quote_events.index("raw_persisted"), quote_events.index("attempt_failed"))
            final = queue.snapshot()
            self.assertEqual(sum(final["status_counts"].values()), final["total"])
            self.assertEqual(final["status_counts"]["SUCCEEDED"], 1)
            self.assertEqual(final["status_counts"]["FAILED"], 4)

    def test_success_is_idempotent_but_configuration_change_creates_new_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            queue = SerialAnnouncementQueue(temp, "announcements", "qwen3_8_flash_next", max_attempts=2)
            original = payload("stable-article")
            first = queue.enqueue(original)
            calls: list[str] = []

            def executor(job: object) -> str:
                calls.append(job.idempotency_key)  # type: ignore[attr-defined]
                return json_executor(job)

            queue.run_pending(executor, pass_validator)
            duplicate = queue.enqueue(original)
            self.assertEqual(first["idempotency_key"], duplicate["idempotency_key"])
            self.assertEqual(duplicate["status"], "SUCCEEDED")
            self.assertEqual(queue.run_pending(executor, pass_validator), [])
            self.assertEqual(len(calls), 1)
            other_queue = SerialAnnouncementQueue(temp, "parallel-queue", "qwen3_8_flash_next", max_attempts=2)
            shared = other_queue.enqueue(original)
            self.assertEqual(shared["idempotency_key"], first["idempotency_key"])
            self.assertEqual(shared["status"], "SUCCEEDED")
            self.assertEqual(other_queue.snapshot()["total"], 1)
            self.assertEqual(other_queue.run_pending(executor, pass_validator), [])
            self.assertEqual(len(calls), 1)

            changed = dict(original)
            changed["configuration_sha256"] = "c" * 64
            fresh = queue.enqueue(changed)
            self.assertNotEqual(first["idempotency_key"], fresh["idempotency_key"])
            self.assertEqual(fresh["status"], "PENDING")
            queue.run_pending(executor, pass_validator)
            self.assertEqual(len(calls), 2)
            self.assertEqual(queue.snapshot()["total"], 2)

    def test_retry_failed_only_retries_failed_items_within_attempt_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            queue = SerialAnnouncementQueue(temp, "announcements", "qwen3_8_flash_next", max_attempts=2)
            queue.enqueue(payload("retry-me", "a"))
            queue.enqueue(payload("already-good", "bb"))
            call_counts: dict[str, int] = {}

            def executor(job: object) -> str:
                article_id = job.payload["article_id"]  # type: ignore[attr-defined]
                call_counts[article_id] = call_counts.get(article_id, 0) + 1
                if article_id == "retry-me" and call_counts[article_id] == 1:
                    raise TimeoutError("injected first-attempt timeout")
                return json_executor(job)

            queue.run_pending(executor, pass_validator)
            snapshot = queue.snapshot()
            failed = next(item for item in snapshot["items"] if item["identity"]["article_id"] == "retry-me")
            good = next(item for item in snapshot["items"] if item["identity"]["article_id"] == "already-good")
            self.assertEqual(failed["status"], "FAILED")
            self.assertEqual(good["status"], "SUCCEEDED")
            self.assertEqual(queue.retry_failed([good["idempotency_key"]]), [])
            self.assertEqual(queue.retry_failed([failed["idempotency_key"]]), [failed["idempotency_key"]])
            queue.run_pending(executor, pass_validator, idempotency_keys=[failed["idempotency_key"]])
            final = {item["identity"]["article_id"]: item for item in queue.snapshot()["items"]}
            self.assertEqual(final["retry-me"]["status"], "SUCCEEDED")
            self.assertEqual(final["retry-me"]["attempt_count"], 2)
            self.assertEqual(final["already-good"]["attempt_count"], 1)
            self.assertEqual(call_counts, {"retry-me": 2, "already-good": 1})

    def test_restart_recovers_running_as_pending_and_never_as_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            queue = SerialAnnouncementQueue(temp, "announcements", "qwen3_8_flash_next", max_attempts=2)
            item = queue.enqueue(payload("interrupted", "full persisted body"))
            state_path = Path(temp) / "queue-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            record = state["jobs"][item["idempotency_key"]]
            record["attempt_count"] = 1
            record["status"] = "RUNNING"
            record["attempts"] = [{
                "number": 1,
                "status": "RUNNING",
                "started_at": "2026-10-14T00:00:00.000Z",
                "finished_at": None,
                "duration_seconds": None,
                "raw_path": None,
                "raw_sha256": None,
                "raw_length_bytes": None,
                "validated_path": None,
                "validated_sha256": None,
                "error": None,
            }]
            state_path.write_text(json.dumps(state), encoding="utf-8")
            crashed_raw = Path(temp) / "jobs" / item["idempotency_key"] / "attempt-0001.raw"
            crashed_raw.write_bytes(b'{"possibly complete but unvalidated":true}')
            os.chmod(crashed_raw, 0o600)

            restarted = SerialAnnouncementQueue(temp, "announcements", "qwen3_8_flash_next", max_attempts=2)
            recovered = restarted.recover_interrupted()
            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0]["status"], "PENDING")
            self.assertEqual(recovered[0]["raw_sha256"], hashlib.sha256(crashed_raw.read_bytes()).hexdigest())
            before_run = restarted.snapshot()["items"][0]
            self.assertEqual(before_run["status"], "PENDING")
            self.assertIsNone(before_run["validated_path"])
            results = restarted.run_pending(json_executor, pass_validator)
            self.assertEqual(len(results), 1)
            self.assertEqual(restarted.snapshot()["status_counts"]["SUCCEEDED"], 1)
            self.assertEqual(restarted.snapshot()["items"][0]["attempt_count"], 2)

    def test_model_slot_is_serial_across_processes_and_queue_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            q_one = SerialAnnouncementQueue(root, "queue-one", "shared-model", max_attempts=2)
            q_two = SerialAnnouncementQueue(root, "queue-two", "shared-model", max_attempts=2)
            q_one.enqueue(payload("process-one", "one", model_id="shared-model"))
            q_two.enqueue(payload("process-two", "two", model_id="shared-model"))
            probe = root / "probe.json"
            probe.write_text(json.dumps({"active": 0, "max_active": 0, "ready": 0, "go": False}), encoding="utf-8")
            child_code = textwrap.dedent(
                """
                import fcntl, json, os, sys, time
                sys.path.insert(0, sys.argv[1])
                from announcement_queue import SerialAnnouncementQueue
                module_dir, state_root, queue_id, probe_path = sys.argv[1:]
                def adjust(delta):
                    with open(probe_path, 'r+', encoding='utf-8') as stream:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                        value = json.load(stream)
                        value['active'] += delta
                        value['max_active'] = max(value['max_active'], value['active'])
                        stream.seek(0); stream.truncate(); json.dump(value, stream)
                        stream.flush(); os.fsync(stream.fileno())
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                def wait_at_barrier():
                    with open(probe_path, 'r+', encoding='utf-8') as stream:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                        value = json.load(stream)
                        value['ready'] += 1
                        stream.seek(0); stream.truncate(); json.dump(value, stream)
                        stream.flush(); os.fsync(stream.fileno())
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                    while True:
                        with open(probe_path, 'r', encoding='utf-8') as stream:
                            fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
                            go = json.load(stream)['go']
                            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                        if go:
                            return
                        time.sleep(0.01)
                def execute(job):
                    adjust(1)
                    time.sleep(0.40)
                    adjust(-1)
                    return json.dumps({'article_id': job.payload['article_id']})
                def validate(job, parsed):
                    if parsed.get('article_id') != job.payload['article_id']:
                        raise ValueError('wrong article')
                    return parsed
                queue = SerialAnnouncementQueue(state_root, queue_id, 'shared-model', max_attempts=2)
                wait_at_barrier()
                outcomes = queue.run_pending(execute, validate)
                assert len(outcomes) == 1 and outcomes[0]['status'] == 'SUCCEEDED'
                """
            )
            command_args = [sys.executable, "-c", child_code]
            processes = [
                subprocess.Popen(command_args + [str(HERE), str(root), queue_id, str(probe)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for queue_id in ("queue-one", "queue-two")
            ]
            deadline = time.monotonic() + 5
            while True:
                with probe.open("r+", encoding="utf-8") as stream:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                    measured = json.load(stream)
                    if measured["ready"] == 2:
                        measured["go"] = True
                        stream.seek(0)
                        stream.truncate()
                        json.dump(measured, stream)
                        stream.flush()
                        os.fsync(stream.fileno())
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                        break
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                if time.monotonic() >= deadline:
                    for process in processes:
                        process.kill()
                    self.fail("both worker processes did not reach the launch barrier")
                time.sleep(0.01)
            outputs = [process.communicate(timeout=10) for process in processes]
            self.assertEqual([process.returncode for process in processes], [0, 0], outputs)
            measured = json.loads(probe.read_text(encoding="utf-8"))
            self.assertEqual(measured["max_active"], 1)
            combined = SerialAnnouncementQueue(root, "queue-one", "shared-model", max_attempts=2).snapshot()
            self.assertEqual(combined["status_counts"]["SUCCEEDED"], 1)
            other = SerialAnnouncementQueue(root, "queue-two", "shared-model", max_attempts=2).snapshot()
            self.assertEqual(other["status_counts"]["SUCCEEDED"], 1)


if __name__ == "__main__":
    unittest.main()
