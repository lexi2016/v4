from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys

AUDIT_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_ANNOUNCEMENT_FULL_AUDIT_20261023")
PHASE2 = AUDIT_ROOT / "resume-20261025" / "phase2"
SCOPE_PATH = PHASE2 / "SCOPE.json"
READBACK_PATH = AUDIT_ROOT / "actual-canary-run" / "runtime-readback" / "ACTUAL_EXECUTION_READBACK.json"
EXPECTED_READBACK_SHA256 = "02a2777be0bce41bf55ef75c1a906a0d3b93de4cd7cfe9449e874a19ef8c0c61"
EXEC_ROOT = AUDIT_ROOT / "canary-input-preparation" / "execution-state"
FLASH_ROOT = EXEC_ROOT / "announcement_flash"
EVIDENCE_ROOT = FLASH_ROOT / "evidence"
QUEUE_ROOT = FLASH_ROOT / "queue"
VERIFIER_PATH = PHASE2 / "verify_saved_readback.py"
NEGATIVE_PATH = PHASE2 / "negative-probe-results.json"
RECONCILED_PATH = PHASE2 / "reconciled-readback.json"
READY_PATH = PHASE2 / "READY_RECEIPT.json"
PANEL_COMMAND_PATH = "/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python"
NO = object()
TRIPLE = ("prompt_tokens", "completion_tokens", "total_tokens")


class Reject(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def need(condition: bool, code: str) -> None:
    if not condition:
        raise Reject(code)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_under(path: Path, root: Path = AUDIT_ROOT) -> bytes:
    if not path.is_absolute():
        raise Reject("PATH_NOT_ABSOLUTE")
    for part in (path, *path.parents):
        if part.is_symlink():
            raise Reject("SYMLINK_INPUT_FORBIDDEN")
    resolved_root = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if resolved == resolved_root or resolved_root not in resolved.parents:
        raise Reject("INPUT_OUTSIDE_AUDIT_ROOT")
    if not resolved.is_file():
        raise Reject("INPUT_NOT_FILE")
    return resolved.read_bytes()


def parse_json(raw: bytes, code: str):
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Reject(code) from exc


def normalized_usage(value: object) -> dict[str, int]:
    need(isinstance(value, dict), "USAGE_OBJECT_MISSING")
    result: dict[str, int] = {}
    for key in TRIPLE:
        token_count = value.get(key)
        need(type(token_count) is int and token_count >= 0, "USAGE_TRIPLE_INVALID")
        result[key] = token_count
    return result


def keepalive_is_provably_empty(event: dict, response_id: str) -> bool:
    expected_top = {"choices", "created", "id", "model", "object"}
    if set(event) != expected_top:
        return False
    if (event.get("model") != "keepalive"
            or event.get("id") != response_id
            or event.get("object") != "chat.completion.chunk"
            or type(event.get("created")) is not int):
        return False
    choices = event.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        return False
    choice = choices[0]
    if not isinstance(choice, dict) or set(choice) != {"delta", "finish_reason", "index"}:
        return False
    if choice.get("index") != 0 or choice.get("finish_reason") is not None:
        return False
    delta = choice.get("delta")
    return (
        isinstance(delta, dict)
        and set(delta) == {"content", "role"}
        and delta.get("content") == ""
        and delta.get("role") == "assistant"
    )


def verify_event_sequence(
    sequence: list,
    *,
    expected_model: str,
    response_id: str,
    expected_raw: bytes,
    usage_reference: dict,
) -> dict:
    markers = [i for i, item in enumerate(sequence) if item is NO]
    need(len(markers) == 1 and markers[0] == len(sequence) - 1, "DONE_MARKER_COUNT")

    counts: dict[str, int] = {}
    keepalive_indices: list[int] = []
    content_parts: list[str] = []
    reasoning_fields: set[str] = set()
    reasoning_characters = 0
    stop_indices: list[int] = []
    usage_indices: list[int] = []
    usage_values: list[dict] = []
    json_index = 0

    for item in sequence:
        if item is NO:
            continue
        need(isinstance(item, dict), "SSE_EVENT_NOT_OBJECT")
        model = item.get("model")
        if model == "keepalive":
            need(keepalive_is_provably_empty(item, response_id), "KEEPALIVE_NOT_EMPTY")
            counts[model] = counts.get(model, 0) + 1
            keepalive_indices.append(json_index)
            json_index += 1
            continue
        need(model == expected_model, "FOREIGN_MODEL")
        need(item.get("id") == response_id, "RESPONSE_ID_MISMATCH")
        counts[model] = counts.get(model, 0) + 1
        choices = item.get("choices")
        need(isinstance(choices, list), "MODEL_CHOICES_INVALID")

        usage = item.get("usage")
        if usage is not None:
            need(not choices, "USAGE_EVENT_HAS_CHOICES")
            usage_indices.append(json_index)
            usage_values.append(usage)
        else:
            for choice in choices:
                need(isinstance(choice, dict), "MODEL_CHOICE_INVALID")
                finish_reason = choice.get("finish_reason")
                if finish_reason == "stop":
                    stop_indices.append(json_index)
                elif finish_reason is not None:
                    raise Reject("UNEXPECTED_FINISH_REASON")
                delta = choice.get("delta") or {}
                need(isinstance(delta, dict), "MODEL_DELTA_INVALID")
                for key, value in delta.items():
                    if key == "content":
                        if value is None:
                            continue
                        need(isinstance(value, str), "MODEL_CONTENT_NOT_TEXT")
                        content_parts.append(value)
                    elif key in ("reasoning_content", "reasoning"):
                        if value is None:
                            continue
                        need(isinstance(value, str), "REASONING_FIELD_NOT_TEXT")
                        reasoning_fields.add(key)
                        reasoning_characters += len(value)
                    elif key == "role":
                        need(value in (None, "assistant"), "MODEL_ROLE_INVALID")
                    elif value not in (None, "", [], {}):
                        raise Reject("UNBOUND_MODEL_DELTA")
        json_index += 1

    need(len(usage_indices) == 1, "USAGE_EVENT_COUNT")
    need(usage_indices[0] == json_index - 1, "USAGE_EVENT_NOT_FINAL")
    need(len(stop_indices) == 1, "STOP_REASON_COUNT")
    need(stop_indices[0] < usage_indices[0], "STOP_REASON_AFTER_USAGE")

    raw_usage = usage_values[0]
    event_triple = normalized_usage(raw_usage)
    reference_triple = normalized_usage(usage_reference)
    need(event_triple == reference_triple, "USAGE_TRIPLE_MISMATCH")

    joined_text = "".join(content_parts)
    joined_bytes = joined_text.encode("utf-8")
    need(joined_bytes == expected_raw, "SSE_CONTENT_RAW_MISMATCH")
    need(bool(joined_bytes), "SSE_CONTENT_EMPTY")

    return {
        "json_event_count": json_index,
        "model_counts": dict(sorted(counts.items())),
        "empty_keepalive_event_indices_zero_based": keepalive_indices,
        "substantive_models": sorted(model for model in counts if model != "keepalive"),
        "content_characters": len(joined_text),
        "content_bytes": len(joined_bytes),
        "content_sha256": sha256(joined_bytes),
        "content_equals_saved_raw": True,
        "stop_finish_reason_count": len(stop_indices),
        "done_marker_count": len(markers),
        "done_is_last": True,
        "usage_event_count": len(usage_indices),
        "normalized_usage": event_triple,
        "usage_event_full_object": raw_usage,
        "reasoning_delta_fields_observed": sorted(reasoning_fields),
        "reasoning_delta_characters_observed": reasoning_characters,
    }


def parse_sse(raw: bytes) -> list:
    blocks = [block for block in re.split(rb"\r?\n\r?\n", raw) if block.strip()]
    sequence: list = []
    for block in blocks:
        data_lines: list[bytes] = []
        for line in block.splitlines():
            if not line:
                continue
            if not line.startswith(b"data:"):
                raise Reject("SSE_UNEXPECTED_FIELD")
            value = line[5:]
            if value.startswith(b" "):
                value = value[1:]
            data_lines.append(value)
        need(len(data_lines) == 1, "SSE_DATA_LINE_COUNT")
        payload = data_lines[0]
        if payload == b"[DONE]":
            sequence.append(NO)
        else:
            event = parse_json(payload, "SSE_JSON_INVALID")
            need(isinstance(event, dict), "SSE_EVENT_NOT_OBJECT")
            sequence.append(event)
    return sequence


def record_probe(name: str, detail: str, expected_code: str, call) -> dict:
    try:
        call()
    except Reject as exc:
        passed = exc.code == expected_code
        if not passed:
            raise Reject(f"NEGATIVE_PROBE_WRONG_REJECTION:{name}:{exc.code}")
        return {
            "name": name,
            "detail": detail,
            "expected_rejection": expected_code,
            "observed_rejection": exc.code,
            "result": "PASS",
        }
    raise Reject(f"NEGATIVE_PROBE_ACCEPTED:{name}")


def clone_sequence(sequence: list) -> list:
    return [deepcopy(item) if isinstance(item, dict) else item for item in sequence]


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def publish(path: Path, value: object, prepared_text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")


if not os.environ.get("PANEL_PYTHON") or not Path(os.environ["PANEL_PYTHON"]).is_absolute():
    raise Reject("PANEL_PYTHON_NOT_ABSOLUTE")
if Path(sys.executable).resolve() != Path(os.environ["PANEL_PYTHON"]).resolve():
    raise Reject("PANEL_PYTHON_RUNTIME_MISMATCH")

scope_raw = read_under(SCOPE_PATH)
scope = parse_json(scope_raw, "SCOPE_JSON_INVALID")
need(scope.get("schema") == "v4.announcement.saved_readback_scope.v1", "SCOPE_SCHEMA_MISMATCH")
need(scope.get("original_readback") == str(READBACK_PATH), "READBACK_PATH_SCOPE_MISMATCH")
need(scope.get("original_readback_sha256") == EXPECTED_READBACK_SHA256, "READBACK_SCOPE_SHA_MISMATCH")
need(scope.get("read_only_execution_root") == str(EXEC_ROOT), "EXECUTION_ROOT_SCOPE_MISMATCH")
need(scope.get("job_id") == "efd3b2f911604e268a8d2d126ff733bf", "JOB_ID_SCOPE_MISMATCH")
need(scope.get("queue_key") == "75c738db9b7681d2ccd854da16ff1f65032910547fb96d6619304e09e5b51309", "QUEUE_KEY_SCOPE_MISMATCH")
need(scope.get("article_id") == "EASTMONEY:AN202610201830727898", "ARTICLE_SCOPE_MISMATCH")
need(scope.get("model_id") == "qwen3_8_flash_next", "MODEL_SCOPE_MISMATCH")
for out_path in (NEGATIVE_PATH, RECONCILED_PATH, READY_PATH):
    if out_path.exists():
        raise FileExistsError(f"require_absent: {out_path}")

readback_raw = read_under(READBACK_PATH)
readback_sha = sha256(readback_raw)
need(readback_sha == EXPECTED_READBACK_SHA256, "ORIGINAL_READBACK_SHA_MISMATCH")
readback = parse_json(readback_raw, "ORIGINAL_READBACK_JSON_INVALID")
need(readback.get("job_id") == scope["job_id"], "READBACK_JOB_ID_MISMATCH")
need(readback.get("queue_key") == scope["queue_key"], "READBACK_QUEUE_KEY_MISMATCH")
need(readback.get("selected_article") == scope["article_id"], "READBACK_ARTICLE_MISMATCH")
need(readback.get("status") == "CANNOT_CONFIRM_INTEGRITY_CHECK", "ORIGINAL_READBACK_STATUS_CHANGED")

known_failures = {"actual_sse_model", "usage_stream_receipt_agree"}
need(set(readback.get("integrity_failures", [])) == known_failures, "UNEXPECTED_ORIGINAL_INTEGRITY_FAILURES")
checks = readback.get("checks")
need(isinstance(checks, dict), "ORIGINAL_CHECKS_INVALID")
false_checks = {key for key, value in checks.items() if value is False}
need(false_checks == known_failures, "UNEXPECTED_FALSE_ORIGINAL_CHECK")
need(all(value is True for key, value in checks.items() if key not in known_failures), "OTHER_ORIGINAL_CHECK_FALSE")

artifact_entries = readback.get("actual_artifact_inventory")
provenance_entries = readback.get("immutable_provenance_refs")
need(isinstance(artifact_entries, list) and len(artifact_entries) == 22, "ARTIFACT_INVENTORY_COUNT_MISMATCH")
need(isinstance(provenance_entries, list) and len(provenance_entries) == 8, "PROVENANCE_INVENTORY_COUNT_MISMATCH")
artifact_bytes: dict[str, bytes] = {}
verified_artifacts: list[dict] = []
for entry in artifact_entries:
    need(isinstance(entry, dict) and {"path", "sha256", "bytes"} <= set(entry), "ARTIFACT_ENTRY_INVALID")
    path = Path(entry["path"])
    path_string = str(path)
    need(path_string not in artifact_bytes, "ARTIFACT_PATH_DUPLICATE")
    raw = read_under(path)
    need(len(raw) == entry["bytes"], "ARTIFACT_BYTE_COUNT_MISMATCH")
    need(sha256(raw) == entry["sha256"], "ARTIFACT_SHA_MISMATCH")
    artifact_bytes[path_string] = raw
    verified_artifacts.append({"path": path_string, "bytes": len(raw), "sha256": sha256(raw)})
provenance_bytes: dict[str, bytes] = {}
verified_provenance: list[dict] = []
for entry in provenance_entries:
    need(isinstance(entry, dict) and {"path", "sha256", "bytes"} <= set(entry), "PROVENANCE_ENTRY_INVALID")
    path = Path(entry["path"])
    path_string = str(path)
    need(path_string not in provenance_bytes, "PROVENANCE_PATH_DUPLICATE")
    raw = read_under(path)
    need(len(raw) == entry["bytes"], "PROVENANCE_BYTE_COUNT_MISMATCH")
    need(sha256(raw) == entry["sha256"], "PROVENANCE_SHA_MISMATCH")
    provenance_bytes[path_string] = raw
    verified_provenance.append({"path": path_string, "bytes": len(raw), "sha256": sha256(raw)})

by_path = {entry["path"]: entry for entry in artifact_entries}


def artifact_path(path: Path) -> bytes:
    path_string = str(path)
    need(path_string in by_path and path_string in artifact_bytes, "REQUIRED_ARTIFACT_NOT_PINNED")
    return artifact_bytes[path_string]


def artifact_json(path: Path, code: str):
    return parse_json(artifact_path(path), code)


stream_receipt_path = EVIDENCE_ROOT / "streams" / scope["queue_key"] / "attempt-0001" / "stream-receipt.json"
stream_sse_path = EVIDENCE_ROOT / "streams" / scope["queue_key"] / "attempt-0001" / "round-01.raw.sse"
request_input_path = EVIDENCE_ROOT / "streams" / scope["queue_key"] / "attempt-0001" / "round-01.request-input.json"
queue_state_path = QUEUE_ROOT / "queue-state.json"
queue_job_path = QUEUE_ROOT / "jobs" / scope["queue_key"] / "attempt-0001.raw"
validated_path = QUEUE_ROOT / "jobs" / scope["queue_key"] / "attempt-0001.validated.json"
delivery_path = Path(readback["delivery"]["path"])
latest_path = FLASH_ROOT / "jobs" / scope["job_id"] / "deliveries" / "latest.json"
terminal_path = EXEC_ROOT / "attempts" / f'{scope["job_id"]}.json'
summary_paths = [Path(p) for p in by_path if "/execution-summaries/" in p]
need(len(summary_paths) == 1, "EXECUTION_SUMMARY_COUNT_MISMATCH")
summary_path = summary_paths[0]

stream_receipt = artifact_json(stream_receipt_path, "STREAM_RECEIPT_JSON_INVALID")
request_raw = artifact_path(request_input_path)
request_input = parse_json(request_raw, "REQUEST_INPUT_JSON_INVALID")
sse_raw = artifact_path(stream_sse_path)
queue_state = artifact_json(queue_state_path, "QUEUE_STATE_JSON_INVALID")
raw_answer = artifact_path(queue_job_path)
validated_raw = artifact_path(validated_path)
validated = parse_json(validated_raw, "VALIDATED_JSON_INVALID")
delivery_raw = artifact_path(delivery_path)
delivery = parse_json(delivery_raw, "DELIVERY_JSON_INVALID")
latest = artifact_json(latest_path, "LATEST_POINTER_JSON_INVALID")
terminal = artifact_json(terminal_path, "TERMINAL_JSON_INVALID")
execution_summary = artifact_json(summary_path, "EXECUTION_SUMMARY_JSON_INVALID")

expected_model = scope["model_id"]
expected_job = scope["job_id"]
expected_queue_key = scope["queue_key"]
expected_article = scope["article_id"]
queue_manifest_entry = by_path[str(queue_job_path)]
validated_manifest_entry = by_path[str(validated_path)]
sse_manifest_entry = by_path[str(stream_sse_path)]
request_manifest_entry = by_path[str(request_input_path)]
delivery_manifest_entry = by_path[str(delivery_path)]
latest_manifest_entry = by_path[str(latest_path)]
terminal_manifest_entry = by_path[str(terminal_path)]
summary_manifest_entry = by_path[str(summary_path)]

need(stream_receipt.get("idempotency_key") == expected_queue_key, "STREAM_QUEUE_KEY_MISMATCH")
need(stream_receipt.get("model_id") == expected_model, "STREAM_MODEL_ID_MISMATCH")
need(stream_receipt.get("response_model") == expected_model, "STREAM_RESPONSE_MODEL_MISMATCH")
need(stream_receipt.get("attempt") == 1 and stream_receipt.get("request_rounds") == 1, "STREAM_ATTEMPT_OR_ROUND_COUNT_MISMATCH")
need(stream_receipt.get("status") == "RESPONSE_RECEIVED" and stream_receipt.get("failure_code") is None, "STREAM_STATUS_MISMATCH")
rounds = stream_receipt.get("rounds")
need(isinstance(rounds, list) and len(rounds) == 1, "STREAM_ROUND_COUNT_MISMATCH")
round_one = rounds[0]
need(round_one.get("round") == 1, "STREAM_ROUND_NUMBER_MISMATCH")
need(round_one.get("raw_sse_path") == f"streams/{expected_queue_key}/attempt-0001/round-01.raw.sse", "STREAM_SSE_PATH_MISMATCH")
need(round_one.get("request_input_path") == f"streams/{expected_queue_key}/attempt-0001/round-01.request-input.json", "STREAM_REQUEST_PATH_MISMATCH")
need(round_one.get("raw_sse_length_bytes") == len(sse_raw), "STREAM_SSE_BYTE_COUNT_MISMATCH")
need(round_one.get("raw_sse_sha256") == sha256(sse_raw) == sse_manifest_entry["sha256"], "STREAM_SSE_SHA_MISMATCH")
need(round_one.get("request_input_length_bytes") == len(request_raw), "STREAM_REQUEST_BYTE_COUNT_MISMATCH")
need(round_one.get("request_input_sha256") == sha256(request_raw) == request_manifest_entry["sha256"], "STREAM_REQUEST_SHA_MISMATCH")
need(request_input.get("model") == expected_model, "REQUEST_MODEL_MISMATCH")
need(request_input.get("stream") is True, "REQUEST_STREAM_FLAG_MISMATCH")
need(request_input.get("stream_options", {}).get("include_usage") is True, "REQUEST_USAGE_STREAM_FLAG_MISMATCH")
wire_intent = readback.get("wire_intent", {})
for key in ("model", "stream", "stream_options", "enable_thinking", "max_tokens", "temperature"):
    need(request_input.get(key) == wire_intent.get(key), f"REQUEST_WIRE_INTENT_MISMATCH:{key}")

response_ids = readback.get("confirmed_response", {}).get("response_ids")
need(isinstance(response_ids, list) and len(response_ids) == 1 and isinstance(response_ids[0], str), "RESPONSE_IDENTITY_MISSING")
response_id = response_ids[0]
sequence = parse_sse(sse_raw)
stream_summary = verify_event_sequence(
    sequence,
    expected_model=expected_model,
    response_id=response_id,
    expected_raw=raw_answer,
    usage_reference=stream_receipt.get("usage"),
)
need(stream_summary["json_event_count"] == 94, "SSE_JSON_EVENT_COUNT_MISMATCH")
need(stream_summary["model_counts"] == {"keepalive": 3, expected_model: 91}, "SSE_MODEL_EVENT_COUNTS_MISMATCH")
need(stream_summary["substantive_models"] == [expected_model], "SSE_SUBSTANTIVE_MODEL_SET_MISMATCH")
confirmed = readback["confirmed_response"]
need(confirmed.get("sse_json_event_count") == stream_summary["json_event_count"], "READBACK_SSE_COUNT_MISMATCH")
need(set(confirmed.get("response_models", [])) == {"keepalive", expected_model}, "READBACK_RESPONSE_MODELS_MISMATCH")
need(confirmed.get("done_markers") == stream_summary["done_marker_count"] == 1, "READBACK_DONE_COUNT_MISMATCH")
need(confirmed.get("finish_reasons") == ["stop"], "READBACK_FINISH_REASON_MISMATCH")
need(confirmed.get("raw_sha256") == sha256(raw_answer), "READBACK_RAW_OUTPUT_SHA_MISMATCH")
need(confirmed.get("reasoning_delta_fields_observed") == stream_summary["reasoning_delta_fields_observed"], "READBACK_REASONING_FIELDS_MISMATCH")
need(confirmed.get("reasoning_delta_characters_observed") == stream_summary["reasoning_delta_characters_observed"], "READBACK_REASONING_COUNT_MISMATCH")
need(len(raw_answer) == queue_manifest_entry["bytes"], "RAW_OUTPUT_BYTE_COUNT_MISMATCH")
need(sha256(raw_answer) == stream_receipt.get("final_text_sha256"), "STREAM_FINAL_TEXT_SHA_MISMATCH")

receipt_usage = normalized_usage(stream_receipt.get("usage"))
round_usage = normalized_usage(round_one.get("usage"))
response_usage_full = confirmed.get("usage")
response_usage = normalized_usage(response_usage_full)
event_usage = normalized_usage(stream_summary["usage_event_full_object"])
need(receipt_usage == round_usage == response_usage == event_usage, "USAGE_TRIPLE_CROSS_SOURCE_MISMATCH")

need(queue_state.get("schema") == "v4.announcement-engine-queue/v1", "QUEUE_STATE_SCHEMA_MISMATCH")
jobs = queue_state.get("jobs")
need(isinstance(jobs, dict) and list(jobs) == [expected_queue_key], "ISOLATED_QUEUE_RECORD_COUNT_MISMATCH")
queue_job = jobs[expected_queue_key]
need(queue_job.get("idempotency_key") == expected_queue_key, "QUEUE_JOB_KEY_MISMATCH")
need(queue_job.get("status") == "SUCCEEDED", "QUEUE_JOB_STATUS_MISMATCH")
need(queue_job.get("attempt_count") == 1 and queue_job.get("max_attempts") == 1, "QUEUE_ATTEMPT_COUNT_MISMATCH")
need(queue_job.get("model_id") == expected_model, "QUEUE_MODEL_MISMATCH")
queue_attempts = queue_job.get("attempts")
need(isinstance(queue_attempts, list) and len(queue_attempts) == 1, "QUEUE_ATTEMPTS_LIST_MISMATCH")
queue_attempt = queue_attempts[0]
need(queue_attempt.get("number") == 1 and queue_attempt.get("status") == "SUCCEEDED", "QUEUE_ATTEMPT_STATUS_MISMATCH")
need(queue_attempt.get("raw_path") == f"jobs/{expected_queue_key}/attempt-0001.raw", "QUEUE_RAW_PATH_MISMATCH")
need(queue_attempt.get("validated_path") == f"jobs/{expected_queue_key}/attempt-0001.validated.json", "QUEUE_VALIDATED_PATH_MISMATCH")
need(queue_attempt.get("raw_sha256") == sha256(raw_answer) == queue_job.get("raw_sha256"), "QUEUE_RAW_SHA_CHAIN_MISMATCH")
need(queue_attempt.get("raw_length_bytes") == len(raw_answer), "QUEUE_RAW_LENGTH_CHAIN_MISMATCH")
if "raw_length_bytes" in queue_job:
    need(queue_job["raw_length_bytes"] == len(raw_answer), "QUEUE_JOB_RAW_LENGTH_MISMATCH")
need(queue_attempt.get("validated_sha256") == sha256(validated_raw) == queue_job.get("validated_sha256"), "QUEUE_VALIDATED_SHA_CHAIN_MISMATCH")
need(queue_job.get("validated_path") == queue_attempt.get("validated_path"), "QUEUE_VALIDATED_PATH_CHAIN_MISMATCH")
need(len(validated.get("results", [])) == 1, "VALIDATED_RESULT_COUNT_MISMATCH")
validated_result = validated["results"][0]
need(validated_result.get("article_id") == expected_article, "VALIDATED_ARTICLE_MISMATCH")

observed = readback.get("observed_execution", {})
need(observed.get("actual_request_rounds") == 1, "OBSERVED_REQUEST_ROUNDS_MISMATCH")
need(observed.get("attempt_count") == 1 and observed.get("actual_lifetime_canary_quota_spent") == 1, "OBSERVED_ATTEMPT_SPENT_MISMATCH")
need(observed.get("quota_remaining") == 0, "OBSERVED_QUOTA_REMAINING_MISMATCH")
need(observed.get("isolated_queue_status") == "SUCCEEDED", "OBSERVED_QUEUE_STATUS_MISMATCH")

need(terminal == readback.get("terminal"), "TERMINAL_READBACK_MISMATCH")
need(terminal.get("job_id") == expected_job, "TERMINAL_JOB_ID_MISMATCH")
need(terminal.get("evidence_kind") == "ISOLATED_EXPLICIT_CANARY", "TERMINAL_EVIDENCE_KIND_MISMATCH")
need(terminal.get("state") == "PARTIAL" and terminal.get("step") == "RETURNED_UNREVIEWED", "TERMINAL_STATE_MISMATCH")

need(delivery.get("schema") == "v4.manager_workbench.announcement_delivery.v1", "DELIVERY_SCHEMA_MISMATCH")
need(delivery.get("job_id") == expected_job, "DELIVERY_JOB_ID_MISMATCH")
need(delivery.get("model_requests_this_invocation") == 1, "DELIVERY_REQUEST_COUNT_MISMATCH")
need(delivery.get("state") == "PARTIAL", "DELIVERY_STATE_MISMATCH")
need(delivery.get("counts") == {"SUCCEEDED": 1}, "DELIVERY_COUNTS_MISMATCH")
need(len(delivery.get("articles", [])) == 1, "DELIVERY_ARTICLE_COUNT_MISMATCH")
delivered_article = delivery["articles"][0]
need(delivered_article.get("article_id") == expected_article, "DELIVERY_ARTICLE_ID_MISMATCH")
need(delivered_article.get("queue_key") == expected_queue_key, "DELIVERY_QUEUE_KEY_MISMATCH")
need(delivered_article.get("state") == "SUCCEEDED", "DELIVERY_ARTICLE_STATE_MISMATCH")
need(delivered_article.get("result_ref") == f"jobs/{expected_queue_key}/attempt-0001.validated.json", "DELIVERY_VALIDATED_REF_MISMATCH")
need(delivered_article.get("result_sha256") == sha256(validated_raw) == validated_manifest_entry["sha256"], "DELIVERY_VALIDATED_SHA_MISMATCH")
need(readback.get("delivery", {}).get("path") == str(delivery_path), "READBACK_DELIVERY_PATH_MISMATCH")
need(readback.get("delivery", {}).get("sha256") == sha256(delivery_raw) == delivery_manifest_entry["sha256"], "READBACK_DELIVERY_SHA_MISMATCH")
need(readback.get("delivery", {}).get("state") == delivery.get("state"), "READBACK_DELIVERY_STATE_MISMATCH")
need(readback.get("delivery", {}).get("model_requests_this_invocation") == delivery.get("model_requests_this_invocation"), "READBACK_DELIVERY_REQUEST_COUNT_MISMATCH")
need(latest.get("schema") == delivery.get("schema"), "LATEST_SCHEMA_MISMATCH")
need(latest.get("job_id") == expected_job, "LATEST_JOB_ID_MISMATCH")
need(latest.get("artifact_ref") == f"announcement_flash/jobs/{expected_job}/deliveries/{delivery_manifest_entry['sha256']}.json", "LATEST_DELIVERY_REF_MISMATCH")
need(latest.get("sha256") == sha256(delivery_raw) == delivery_manifest_entry["sha256"], "LATEST_DELIVERY_SHA_MISMATCH")

need(execution_summary.get("job_id") == expected_job, "EXECUTION_SUMMARY_JOB_MISMATCH")
need(execution_summary.get("model_id") == expected_model, "EXECUTION_SUMMARY_MODEL_MISMATCH")
need(execution_summary.get("state") == "PARTIAL", "EXECUTION_SUMMARY_STATE_MISMATCH")
need(execution_summary.get("review_status") == "MODEL_CANDIDATE_UNREVIEWED", "EXECUTION_SUMMARY_REVIEW_STATUS_MISMATCH")
need(execution_summary.get("classification_execution", {}).get("queue_dispatches_observed") == 1, "EXECUTION_SUMMARY_DISPATCH_COUNT_MISMATCH")
need(sha256(artifact_bytes[str(summary_path)]) == summary_manifest_entry["sha256"], "EXECUTION_SUMMARY_SHA_MISMATCH")

safety = readback.get("safety", {})
need(safety.get("RESEARCH_ONLY") is True and safety.get("production_allowed") is False
     and safety.get("buy_gate_updated") is False and safety.get("orders_sent") is False,
     "SAVED_RESEARCH_SAFETY_FLAGS_MISMATCH")
delivery_safety = delivery.get("safety", {})
for safety_key in ("RESEARCH_ONLY", "production_allowed", "buy_gate_updated", "orders_sent"):
    need(delivery_safety.get(safety_key) == safety.get(safety_key), f"DELIVERY_SAFETY_FLAGS_MISMATCH:{safety_key}")

probes: list[dict] = []
foreign_sequence = clone_sequence(sequence)
foreign_event = next(item for item in foreign_sequence if isinstance(item, dict)
                     and item.get("model") == expected_model
                     and any(isinstance(c, dict) and isinstance((c.get("delta") or {}).get("content"), str)
                             and (c.get("delta") or {}).get("content") for c in item.get("choices", [])))
foreign_event["model"] = "foreign-model"
probes.append(record_probe(
    "foreign_model_with_substantive_text",
    "A foreign model event carrying nonempty text must be rejected.",
    "FOREIGN_MODEL",
    lambda: verify_event_sequence(foreign_sequence, expected_model=expected_model, response_id=response_id,
                                  expected_raw=raw_answer, usage_reference=round_one["usage"]),
))

keepalive_content_sequence = clone_sequence(sequence)
keepalive_event = next(item for item in keepalive_content_sequence if isinstance(item, dict) and item.get("model") == "keepalive")
keepalive_event["choices"][0]["delta"]["content"] = "x"
probes.append(record_probe(
    "keepalive_with_substantive_content",
    "A keepalive with nonempty content must not be excluded as an empty keepalive.",
    "KEEPALIVE_NOT_EMPTY",
    lambda: verify_event_sequence(keepalive_content_sequence, expected_model=expected_model, response_id=response_id,
                                  expected_raw=raw_answer, usage_reference=round_one["usage"]),
))

keepalive_reasoning_sequence = clone_sequence(sequence)
keepalive_reasoning_event = next(item for item in keepalive_reasoning_sequence if isinstance(item, dict) and item.get("model") == "keepalive")
keepalive_reasoning_event["choices"][0]["delta"]["reasoning_content"] = "x"
probes.append(record_probe(
    "keepalive_with_reasoning",
    "A keepalive with any reasoning payload must be rejected.",
    "KEEPALIVE_NOT_EMPTY",
    lambda: verify_event_sequence(keepalive_reasoning_sequence, expected_model=expected_model, response_id=response_id,
                                  expected_raw=raw_answer, usage_reference=round_one["usage"]),
))

usage_drift = dict(round_one["usage"])
usage_drift["prompt_tokens"] += 1
probes.append(record_probe(
    "normalized_usage_drift",
    "Changing one field in the normalized token triple must be rejected.",
    "USAGE_TRIPLE_MISMATCH",
    lambda: verify_event_sequence(sequence, expected_model=expected_model, response_id=response_id,
                                  expected_raw=raw_answer, usage_reference=usage_drift),
))

done_position = next(i for i, item in enumerate(sequence) if item is NO)
missing_done = sequence[:done_position]
probes.append(record_probe(
    "terminal_done_missing",
    "Missing [DONE] must be rejected.",
    "DONE_MARKER_COUNT",
    lambda: verify_event_sequence(missing_done, expected_model=expected_model, response_id=response_id,
                                  expected_raw=raw_answer, usage_reference=round_one["usage"]),
))
duplicate_done = list(sequence) + [NO]
probes.append(record_probe(
    "terminal_done_duplicated",
    "Repeated [DONE] must be rejected.",
    "DONE_MARKER_COUNT",
    lambda: verify_event_sequence(duplicate_done, expected_model=expected_model, response_id=response_id,
                                  expected_raw=raw_answer, usage_reference=round_one["usage"]),
))

missing_stop = clone_sequence(sequence)
stop_event = next(item for item in missing_stop if isinstance(item, dict)
                  and any(isinstance(choice, dict) and choice.get("finish_reason") == "stop"
                          for choice in item.get("choices", [])))
next(choice for choice in stop_event["choices"] if choice.get("finish_reason") == "stop")["finish_reason"] = None
probes.append(record_probe(
    "terminal_stop_missing",
    "Missing stop finish_reason must be rejected.",
    "STOP_REASON_COUNT",
    lambda: verify_event_sequence(missing_stop, expected_model=expected_model, response_id=response_id,
                                  expected_raw=raw_answer, usage_reference=round_one["usage"]),
))

duplicate_stop = clone_sequence(sequence)
stop_events = [item for item in duplicate_stop if isinstance(item, dict)
               and any(isinstance(choice, dict) and choice.get("finish_reason") == "stop"
                       for choice in item.get("choices", []))]
next_stop_choice = next(choice for item in duplicate_stop if isinstance(item, dict)
                        and item.get("model") == expected_model
                        for choice in item.get("choices", [])
                        if isinstance(choice, dict) and choice.get("finish_reason") is None)
next_stop_choice["finish_reason"] = "stop"
probes.append(record_probe(
    "terminal_stop_duplicated",
    "Repeated stop finish_reason must be rejected.",
    "STOP_REASON_COUNT",
    lambda: verify_event_sequence(duplicate_stop, expected_model=expected_model, response_id=response_id,
                                  expected_raw=raw_answer, usage_reference=round_one["usage"]),
))
need(len(probes) == 8 and all(item["result"] == "PASS" for item in probes), "NEGATIVE_PROBES_FAILED")

event_usage_full = stream_summary["usage_event_full_object"]
stream_receipt_usage = stream_receipt["usage"]
readback_usage_extended = {key: value for key, value in response_usage_full.items() if key not in TRIPLE}
event_usage_extended = {key: value for key, value in event_usage_full.items() if key not in TRIPLE}
need(event_usage_extended, "STREAM_USAGE_EXTENSIONS_MISSING")

reconciled = {
    "schema": "v4.announcement.saved_readback_reconciliation.v1",
    "status": "RECONCILED_FOR_TWO_KNOWN_INTEGRITY_DIFFERENCES",
    "scope_path": str(SCOPE_PATH),
    "scope_sha256": sha256(scope_raw),
    "original_readback": {
        "path": str(READBACK_PATH),
        "bytes": len(readback_raw),
        "sha256": readback_sha,
        "pinned_sha256": EXPECTED_READBACK_SHA256,
        "status_preserved": readback["status"],
        "integrity_failures_preserved": sorted(readback["integrity_failures"]),
        "file_modified": False,
    },
    "reconciled_differences": [
        {
            "old_check": "actual_sse_model",
            "old_value": False,
            "corrected_value": True,
            "rule": "Only a keepalive event with exact known empty structure, empty content, assistant role metadata, null finish reason, no usage, and matching response id is excluded from model-bearing events.",
            "event_counts": stream_summary["model_counts"],
            "substantive_models": stream_summary["substantive_models"],
            "keepalive_indices_zero_based": stream_summary["empty_keepalive_event_indices_zero_based"],
        },
        {
            "old_check": "usage_stream_receipt_agree",
            "old_value": False,
            "corrected_value": True,
            "rule": "Compare prompt_tokens, completion_tokens, and total_tokens only; preserve all extended event/readback usage fields as evidence.",
            "normalized_usage": stream_summary["normalized_usage"],
            "stream_receipt_extended_fields": sorted(key for key in stream_receipt_usage if key not in TRIPLE),
            "event_extended_usage": event_usage_extended,
            "readback_extended_usage": readback_usage_extended,
        },
    ],
    "sse_reconciliation": {
        "raw_sse_path": str(stream_sse_path),
        "raw_sse_bytes": len(sse_raw),
        "raw_sse_sha256": sha256(sse_raw),
        "stream_receipt_json_rounds": stream_receipt["request_rounds"],
        "json_event_count": stream_summary["json_event_count"],
        "model_counts": stream_summary["model_counts"],
        "content_characters": stream_summary["content_characters"],
        "content_bytes": stream_summary["content_bytes"],
        "content_sha256": stream_summary["content_sha256"],
        "content_equals_saved_raw": stream_summary["content_equals_saved_raw"],
        "finish_reason_stop_count": stream_summary["stop_finish_reason_count"],
        "done_marker_count": stream_summary["done_marker_count"],
        "done_is_last": stream_summary["done_is_last"],
        "reasoning_delta_fields_observed": stream_summary["reasoning_delta_fields_observed"],
        "reasoning_delta_characters_observed": stream_summary["reasoning_delta_characters_observed"],
    },
    "historical_execution_accounting": {
        "evidence_timestamp_utc": readback.get("created_at_utc"),
        "evidence_kind": terminal.get("evidence_kind"),
        "job_id": expected_job,
        "queue_key": expected_queue_key,
        "article_id": expected_article,
        "model_id": expected_model,
        "request_rounds": observed["actual_request_rounds"],
        "attempts_spent": observed["actual_lifetime_canary_quota_spent"],
        "attempt_count": observed["attempt_count"],
        "quota_remaining": observed["quota_remaining"],
        "status_is_historical_not_current": True,
    },
    "hash_chain": {
        "request_input": {"path": str(request_input_path), "bytes": len(request_raw), "sha256": sha256(request_raw)},
        "stream_receipt": {"path": str(stream_receipt_path), "bytes": by_path[str(stream_receipt_path)]["bytes"], "sha256": by_path[str(stream_receipt_path)]["sha256"]},
        "raw_sse": {"path": str(stream_sse_path), "bytes": len(sse_raw), "sha256": sha256(sse_raw)},
        "model_text_raw": {"path": str(queue_job_path), "bytes": len(raw_answer), "sha256": sha256(raw_answer)},
        "queue_state": {"path": str(queue_state_path), "bytes": by_path[str(queue_state_path)]["bytes"], "sha256": by_path[str(queue_state_path)]["sha256"]},
        "validated": {"path": str(validated_path), "bytes": len(validated_raw), "sha256": sha256(validated_raw)},
        "delivery": {"path": str(delivery_path), "bytes": len(delivery_raw), "sha256": sha256(delivery_raw)},
        "latest_pointer": {"path": str(latest_path), "bytes": len(artifact_path(latest_path)), "sha256": sha256(artifact_path(latest_path))},
        "terminal": {"path": str(terminal_path), "bytes": len(artifact_path(terminal_path)), "sha256": sha256(artifact_path(terminal_path))},
        "execution_summary": {"path": str(summary_path), "bytes": len(artifact_path(summary_path)), "sha256": sha256(artifact_path(summary_path))},
        "validated_semantic_equality_claimed": False,
        "validated_binding_rule": "Queue state binds the persisted raw and validated hashes; delivery binds the validated result reference and SHA. This phase does not regrade model semantics.",
    },
    "pinned_inputs": {
        "artifact_inventory_count": len(verified_artifacts),
        "artifacts_verified": verified_artifacts,
        "immutable_provenance_count": len(verified_provenance),
        "immutable_provenance_verified": verified_provenance,
    },
    "negative_probes": {
        "path": str(NEGATIVE_PATH),
        "count": len(probes),
        "all_passed": True,
    },
    "CANNOT_CONFIRM": list(dict.fromkeys(list(readback.get("CANNOT_CONFIRM", [])) + list(scope.get("evidence_limits", [])))),
    "not_run": [
        "original readback.py",
        "HTTP/model/tokenizer/preprocessing/source capture",
        "business runner, production queue, queue claim/write",
        "services, current live model settings, deployment",
        "old14 regrading, old canary replay, 201 pending items",
        "semantic business review, official publication/PIT, natural-slot acceptance",
        "Git actions",
    ],
}

negative_report = {
    "schema": "v4.announcement.saved_readback_negative_probes.v1",
    "mode": "PURE_OFFLINE_IN_MEMORY_MUTATIONS_ONLY",
    "input_raw_sse_sha256": sha256(sse_raw),
    "probes": probes,
    "passed_count": len(probes),
    "failed_count": 0,
    "all_passed": True,
}

verifier_sha = sha256(VERIFIER_PATH.read_bytes())
command = (
    "PYTHONDONTWRITEBYTECODE=1 "
    f"'{PANEL_COMMAND_PATH}' -B '{VERIFIER_PATH}'"
)
ready = {
    "schema": "v4.announcement.phase2.ready_receipt.v1",
    "result": "READY_FOR_INDEPENDENT_REVIEW",
    "phase": "PHASE2_SAVED_READBACK_RECONCILIATION",
    "scope_path": str(SCOPE_PATH),
    "scope_sha256": sha256(scope_raw),
    "writer": "/root/announcement_recovery_writer",
    "reviewer": "/root/announcement_recovery_review",
    "verification_script": {"path": str(VERIFIER_PATH), "sha256": verifier_sha},
    "execution": {
        "command": command,
        "PANEL_PYTHON_environment_value": os.environ["PANEL_PYTHON"],
        "resolved_sys_executable": str(Path(sys.executable).resolve()),
        "python_version": platform.python_version(),
        "subprocesses": 0,
        "network_calls": 0,
        "business_writes": 0,
    },
    "original_readback": {
        "path": str(READBACK_PATH),
        "pinned_sha256": EXPECTED_READBACK_SHA256,
        "verified_sha256": readback_sha,
        "original_status_preserved": readback["status"],
    },
    "result_summary": {
        "artifact_hashes": f'{len(verified_artifacts)}/{len(verified_artifacts)}',
        "immutable_provenance_hashes": f'{len(verified_provenance)}/{len(verified_provenance)}',
        "sse_content_raw_match": True,
        "empty_keepalive_events_excluded": len(stream_summary["empty_keepalive_event_indices_zero_based"]),
        "substantive_model_events": stream_summary["model_counts"].get(expected_model, 0),
        "normalized_usage_triple": stream_summary["normalized_usage"],
        "request_rounds": observed["actual_request_rounds"],
        "attempts_spent": observed["actual_lifetime_canary_quota_spent"],
        "quota_remaining": observed["quota_remaining"],
        "negative_probes": f"{len(probes)}/{len(probes)}",
    },
    "outputs": {
        "negative_probe_results": {"path": str(NEGATIVE_PATH), "sha256": sha256(json_text(negative_report).encode("utf-8"))},
        "reconciled_readback": {"path": str(RECONCILED_PATH), "sha256": sha256(json_text(reconciled).encode("utf-8"))},
    },
    "limits": {
        "independent_review": "PENDING",
        "semantic_business_acceptance": "NOT_CLAIMED",
        "production_or_current_queue_state": "NOT_CLAIMED",
        "historical_http_status_hidden_model_state_official_publication_pit_natural_slot": "CANNOT_CONFIRM",
    },
    "not_run": reconciled["not_run"],
}

negative_text = json_text(negative_report)
reconciled_text = json_text(reconciled)
ready_text = json_text(ready)
# Parse each completed artifact once before any output is published.
negative_parsed = json.loads(negative_text)
reconciled_parsed = json.loads(reconciled_text)
ready_parsed = json.loads(ready_text)
need(negative_parsed == negative_report, "NEGATIVE_JSON_ROUNDTRIP_MISMATCH")
need(reconciled_parsed == reconciled, "RECONCILED_JSON_ROUNDTRIP_MISMATCH")
need(ready_parsed == ready, "READY_JSON_ROUNDTRIP_MISMATCH")
for out_path in (NEGATIVE_PATH, RECONCILED_PATH, READY_PATH):
    if out_path.exists():
        raise FileExistsError(f"require_absent: {out_path}")
publish(NEGATIVE_PATH, negative_parsed, negative_text)
publish(RECONCILED_PATH, reconciled_parsed, reconciled_text)
publish(READY_PATH, ready_parsed, ready_text)
print(json.dumps({
    "result": ready["result"],
    "ready_receipt": str(READY_PATH),
    "reconciled_readback": str(RECONCILED_PATH),
    "negative_probes": str(NEGATIVE_PATH),
    "verified_artifacts": len(verified_artifacts),
    "verified_provenance": len(verified_provenance),
    "sse_events": stream_summary["json_event_count"],
    "model_counts": stream_summary["model_counts"],
    "usage_triple": stream_summary["normalized_usage"],
    "negative_probe_count": len(probes),
    "python_version": platform.python_version(),
}, ensure_ascii=False, sort_keys=True))
