"""Run one frozen, sandboxed ACT-072M case or a no-decode readiness check."""

from __future__ import annotations

import argparse
import os
import random
import re
import resource
import subprocess
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from tempfile import mkdtemp

from research.act070a.case_contract import Rejected, json_bytes, require, sha256
from research.act072m.contract import (
    ATTACHMENTS, CASE_ID_PATTERN, INPUT_LOCK_NAME, MAX_TOKENS, PROMPT_SHA256, RUNTIME_VERSION, SAFE_EXECUTABLE,
    SAFE_GUARDS, SEED, TEMPERATURE, check_case, check_model, check_runtime, file_sha256, prove_network_denial,
    read_object, regular_local, sandbox_profile, write_object,
)

OUTER_FENCE = re.compile(rb"\A```(?:json)?\r?\n(.*?)\r?\n```(?:\r?\n)?\Z", re.DOTALL)
INNER_FENCE_CLOSE = re.compile(rb"^ {0,3}`{3,}[ \t]*\r?$", re.MULTILINE)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def remove_outer_fence(raw: bytes) -> tuple[bytes, str]:
    match = OUTER_FENCE.fullmatch(raw)
    if match and not INNER_FENCE_CLOSE.search(match.group(1)):
        return match.group(1), "EXACT_OUTER_FENCE_REMOVED"
    return raw, "IDENTITY"


def user_message(prompt: str, text_attachments: dict[str, str]) -> list[dict]:
    """One user turn. File markers carry attachment names, outside the frozen instruction."""
    content = [{"type": "text", "text": prompt}, {"type": "image"}]
    for name in ATTACHMENTS[1:]:
        content.append({"type": "text", "text": f"\n<attachment filename=\"{name}\">\n{text_attachments[name]}\n</attachment>\n"})
    return [{"role": "user", "content": content}]


def child_environment(result: Path) -> dict:
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8",
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": str(SEED),
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1", "TOKENIZERS_PARALLELISM": "false",
        "HF_HOME": str(result / "hf"), "XDG_CACHE_HOME": str(result / "cache"), "TMPDIR": str(result),
    }


def _read_case_for_worker(case: dict):
    case_dir = Path(case["case_dir"])
    payloads = {}
    for name in ATTACHMENTS:
        raw = regular_local(case_dir / name).read_bytes()
        require(sha256(raw) == case["attachment_sha256"][name], "FROZEN_ATTACHMENT_HASH_MISMATCH", name)
        payloads[name] = raw
    prompt = regular_local(Path(case["prompt"])).read_bytes()
    require(sha256(prompt) == PROMPT_SHA256, "FROZEN_PROMPT_HASH_MISMATCH", "worker prompt")
    payloads.pop("chart.png")  # The vision loader receives only the pinned PNG path.
    return (case_dir / "chart.png",
            user_message(prompt.decode("utf-8"), {name: raw.decode("utf-8") for name, raw in payloads.items()}))


def _infer_once(model, processor, case: dict, result_dir: Path, measurements: dict) -> None:
    from mlx_vlm import stream_generate

    image, messages = _read_case_for_worker(case)
    template = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    require(isinstance(template, str) and template.count("<|image_pad|>") == 1
            and all(item["text"] in template for item in messages[0]["content"] if item["type"] == "text"),
            "NATIVE_TEMPLATE_INTEGRITY_MISMATCH", "single image and exact frozen prompt/text attachments")
    measurements["formatted_prompt_sha256"] = sha256(template.encode("utf-8"))
    measurements["user_turn_count"] = 1
    measurements["attachments_count"] = len(ATTACHMENTS)
    raw_path = result_dir / f"{case['case_id']}_raw.txt"
    with raw_path.open("xb", buffering=0) as raw:
        write_object(result_dir / "decode_started.json", {"started_utc": utc_now(), "invocations": 1})
        start = time.perf_counter()
        measurements["model_inference_calls"] = 1
        try:
            chunks = stream_generate(model, processor, template, image=[str(image)], max_tokens=MAX_TOKENS,
                                     temperature=TEMPERATURE, prompt_cache=None, prompt_cache_state=None,
                                     vision_cache=None, apc_manager=None)
            for chunk in chunks:
                raw.write(chunk.text.encode("utf-8"))
                measurements["prompt_tokens"] = chunk.prompt_tokens
                measurements["generation_tokens"] = chunk.generation_tokens
                measurements["cached_tokens"] = chunk.cached_tokens
                measurements["finish_reason"] = chunk.finish_reason
                require(chunk.cached_tokens == 0, "CROSS_CASE_CACHE_REUSE", str(chunk.cached_tokens))
            measurements["generation_completed"] = True
        finally:
            measurements["generation_wall_seconds"] = time.perf_counter() - start
            os.fsync(raw.fileno())


def worker(spec: Path, digest: str) -> int:
    regular_local(spec)
    require(file_sha256(spec) == digest, "WORKER_SPEC_HASH_MISMATCH", spec.name)
    locked = read_object(spec)
    result_dir = spec.parent
    write_object(result_dir / "worker_started.json", {"process_id": os.getpid(), "started_utc": utc_now()})
    case = locked["case"]
    started = time.perf_counter()
    measurements = {
        "status": "FAILED", "case_id": case["case_id"] if case else None,
        "mode": "OFFLINE_CASE_INFERENCE" if case else "OFFLINE_MODEL_LOAD_ONLY",
        "framework": f"mlx-vlm=={RUNTIME_VERSION}", "process_id": os.getpid(),
        "model_initialization_calls": 0, "model_inference_calls": 0, "generation_completed": False,
        "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS, "seed": SEED, **SAFE_GUARDS,
    }
    mx = None
    try:
        measurements["network_sandbox_check"] = prove_network_denial()
        require(os.environ.get("HF_HUB_OFFLINE") == os.environ.get("TRANSFORMERS_OFFLINE") == "1",
                "OFFLINE_RUNTIME_NOT_ENFORCED", "offline provider configuration")
        import mlx.core as mx
        from mlx_vlm import load

        random.seed(SEED)
        mx.random.seed(SEED)
        load_started = time.perf_counter()
        measurements["model_initialization_calls"] = 1
        try:
            model, processor = load(locked["model_dir"], trust_remote_code=False, local_files_only=True)
        finally:
            measurements["model_load_wall_seconds"] = time.perf_counter() - load_started
        measurements["processor_has_chat_template"] = callable(getattr(processor, "apply_chat_template", None))
        require(measurements["processor_has_chat_template"], "CHAT_TEMPLATE_UNAVAILABLE", type(processor).__name__)
        if case:
            _infer_once(model, processor, case, result_dir, measurements)
        measurements["status"] = "PASS"
        return 0
    except BaseException as exc:
        measurements["error_type"] = type(exc).__name__
        traceback.print_exc()
        return 1
    finally:
        measurements["worker_wall_seconds"] = time.perf_counter() - started
        measurements["peak_mac_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        measurements["peak_mlx_memory_bytes"] = None
        if mx is not None:
            try:
                measurements["peak_mlx_memory_bytes"] = mx.get_peak_memory()
            except (RuntimeError, OSError) as exc:
                measurements["mlx_memory_metric_error"] = type(exc).__name__
        write_object(result_dir / "metrics.json", measurements)


def _launch(stage: Path, result: Path, runtime: Path, model_dir: Path, model_identity: dict, case: dict | None) -> int:
    start = time.perf_counter()
    spec = result / "worker_spec.json"
    write_object(spec, {"case": case, "model_dir": str(model_dir)})
    write_object(result / "attempt.json", {"case_id": case["case_id"] if case else None, "status": "RESERVED",
                 "started_utc": utc_now(), "model": model_identity, "input": case, **SAFE_GUARDS})
    profile = sandbox_profile(stage, result, model_dir, case)
    command = [str(SAFE_EXECUTABLE), "-p", profile, str(runtime), "-B", "-m", "research.act072m.run_case",
               "_worker", "--spec", str(spec), "--digest", file_sha256(spec)]
    rc, launch_error = None, None
    try:
        with (result / "worker.stdout.log").open("xb") as stdout, (result / "worker.stderr.log").open("xb") as stderr:
            rc = subprocess.run(command, env=child_environment(result), stdin=subprocess.DEVNULL,
                                stdout=stdout, stderr=stderr, check=False).returncode
    except BaseException as exc:
        launch_error = type(exc).__name__
        raise
    finally:
        summary = {"exit_code": rc, "launch_error_type": launch_error, "ended_utc": utc_now(),
                   "sandbox_profile_sha256": sha256(profile.encode("utf-8")),
                   "parent_wall_seconds": time.perf_counter() - start}
        if case:
            case_id = case["case_id"]
            raw_path, response_path = result / f"{case_id}_raw.txt", result / f"{case_id}.json"
            if not raw_path.exists():
                with raw_path.open("xb"):
                    pass
            raw = raw_path.read_bytes()
            response, transform = remove_outer_fence(raw)
            with response_path.open("xb") as handle:
                handle.write(response)
                handle.flush()
                os.fsync(handle.fileno())
            summary.update({"case_id": case_id, "raw_sha256": sha256(raw), "response_sha256": sha256(response),
                            "raw_bytes": len(raw), "response_bytes": len(response), "response_transform": transform,
                            "decode_started_marker_present": (result / "decode_started.json").is_file(),
                            "worker_metrics_present": (result / "metrics.json").is_file()})
        write_object(result / "launch_receipt.json", summary)
    return rc


def reserve_attempt(stage: Path, case_id: str) -> Path:
    require(CASE_ID_PATTERN.fullmatch(case_id), "INVALID_CASE_ID", case_id)
    attempts = stage / "attempts"
    attempts.mkdir(exist_ok=True)
    require(attempts.resolve(strict=True) == attempts, "INVALID_ATTEMPTS_PATH", attempts.name)
    result = attempts / case_id
    try:
        result.mkdir()
    except FileExistsError as exc:
        raise Rejected("CASE_ALREADY_RESERVED", case_id) from exc
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    for name in ("preflight", "infer", "smoke-load"):
        command = commands.add_parser(name)
        command.add_argument("--stage-dir", type=Path, required=True)
        if name != "smoke-load":
            command.add_argument("--case-dir", type=Path, required=True)
            command.add_argument("--input-lock", type=Path)
    internal = commands.add_parser("_worker")
    internal.add_argument("--spec", type=Path, required=True)
    internal.add_argument("--digest", required=True)
    args = parser.parse_args()
    if args.mode == "_worker":
        return worker(args.spec, args.digest)

    stage = args.stage_dir.absolute()
    try:
        runtime = check_runtime(stage)
        model_dir, model = check_model(stage)
        if args.mode == "smoke-load":
            result = Path(mkdtemp(prefix="runtime-smoke-", dir=stage))
            rc = _launch(stage, result, runtime, model_dir, model, None)
            print(json_bytes({"mode": "LOAD_ONLY_NO_CASE", "result": str(result), "exit_code": rc}).decode())
            return rc
        case = check_case(stage, args.case_dir.absolute(), (args.input_lock or stage / INPUT_LOCK_NAME).absolute())
        if args.mode == "preflight":
            print(json_bytes({"status": "PASS", "case_id": case["case_id"], "model_inference_calls": 0,
                             "prompt_sha256": case["prompt_sha256"], "attachment_count": len(ATTACHMENTS)}).decode())
            return 0
        result = reserve_attempt(stage, case["case_id"])
        rc = _launch(stage, result, runtime, model_dir, model, case)
        print(json_bytes({"case_id": case["case_id"], "result": str(result), "exit_code": rc}).decode())
        return rc
    except (Rejected, OSError, ValueError, KeyError) as exc:
        print(json_bytes({"status": "BLOCKED", "code": getattr(exc, "code", type(exc).__name__),
                         "detail": str(exc)[:280]}).decode())
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
