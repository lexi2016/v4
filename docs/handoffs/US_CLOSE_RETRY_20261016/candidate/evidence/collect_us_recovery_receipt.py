#!/usr/bin/env python3
"""Run a planned US recovery command and save a bounded, no-overwrite receipt."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
PROXY_ENV = (
    "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy",
)


def digest_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def copy_capped(source: BinaryIO, destination: BinaryIO, cap: int) -> tuple[int, str, bool]:
    total = 0
    kept = 0
    digest = hashlib.sha256()
    while True:
        chunk = source.read(65536)
        if not chunk:
            break
        total += len(chunk)
        digest.update(chunk)
        if kept < cap:
            take = chunk[: cap - kept]
            destination.write(take)
            kept += len(take)
    destination.flush()
    os.fsync(destination.fileno())
    return total, digest.hexdigest(), total > kept


def parse_output(path: Path, truncated: bool) -> dict | None:
    if truncated:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt-dir", type=Path, required=True)
    parser.add_argument("--candidate-app-root", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--candidate-manifest-sha256", required=True)
    parser.add_argument("--producer-source", type=Path, required=True)
    parser.add_argument("--max-stream-bytes", type=int, default=1_048_576)
    parser.add_argument("--run-id", help="Optional deterministic ID for collision testing; collisions fail closed.")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")
    if args.max_stream_bytes < 0:
        parser.error("--max-stream-bytes must be nonnegative")
    # Use a timezone-independent suffix: local numeric offsets (for example
    # +0800) are outside SAFE_RUN_ID and made the default fail before capture.
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex
    if not SAFE_RUN_ID.fullmatch(run_id) or run_id in {".", ".."}:
        parser.error("invalid --run-id")

    args.receipt_dir.mkdir(parents=True, exist_ok=True)
    run_dir = args.receipt_dir / run_id
    try:
        run_dir.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError:
        # Preserve the colliding run's existing receipt and persist this
        # rejected attempt under a fresh exclusive directory.
        requested_run_id = run_id
        run_id = f"collision-{uuid.uuid4().hex}"
        run_dir = args.receipt_dir / run_id
        run_dir.mkdir(mode=0o700, exist_ok=False)
        stdout_path = run_dir / "stdout.bin"
        stderr_path = run_dir / "stderr.bin"
        stdout_path.open("xb").close()
        stderr_path.open("xb").close()
        receipt_path = run_dir / "receipt.json"
        receipt_sha_path = run_dir / "receipt.sha256"
        empty_sha = hashlib.sha256(b"").hexdigest()
        receipt = {
            "schema": "us_close_recovery_capture_receipt.v1",
            "run_id": run_id,
            "requested_run_id": requested_run_id,
            "status": "RECEIPT_COLLISION",
            "started_at_utc": utc_now(),
            "finished_at_utc": utc_now(),
            "candidate_app_root": str(args.candidate_app_root),
            "candidate_manifest_path": str(args.candidate_manifest),
            "candidate_manifest_sha256_actual": digest_file(args.candidate_manifest),
            "candidate_manifest_sha256_expected": args.candidate_manifest_sha256.lower(),
            "producer_source_path": str(args.producer_source),
            "producer_source_sha256": digest_file(args.producer_source),
            "command": command,
            "producer_started": False,
            "preflight_error": "RECEIPT_RUN_ID_COLLISION",
            "exit_code": 73,
            "proxy_environment": {name: os.environ.get(name) for name in PROXY_ENV},
            "research_safety_flags": {name: os.environ.get(name) for name in ("RESEARCH_ONLY", "PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT")},
            "stdout": {"path": stdout_path.name, "bytes_total": 0, "sha256_full_stream": empty_sha, "bytes_persisted": 0, "truncated": False},
            "stderr": {"path": stderr_path.name, "bytes_total": 0, "sha256_full_stream": empty_sha, "bytes_persisted": 0, "truncated": False},
            "receipt_sha256_path": receipt_sha_path.name,
        }
        payload = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        with receipt_path.open("xb") as handle:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        receipt_hash = hashlib.sha256(payload).hexdigest()
        with receipt_sha_path.open("xb") as handle:
            handle.write(f"{receipt_hash}  {receipt_path.name}\n".encode("ascii")); handle.flush(); os.fsync(handle.fileno())
        print(json.dumps({"status": "RECEIPT_COLLISION", "run_id": requested_run_id, "receipt": str(receipt_path), "receipt_sha256": receipt_hash, "exit_code": 73}, sort_keys=True))
        return 73

    stdout_path = run_dir / "stdout.bin"
    stderr_path = run_dir / "stderr.bin"
    receipt_path = run_dir / "receipt.json"
    receipt_sha_path = run_dir / "receipt.sha256"
    manifest_sha = digest_file(args.candidate_manifest)
    source_path = args.producer_source
    source_sha = digest_file(source_path)
    expected_manifest = args.candidate_manifest_sha256.lower()
    preflight_error = None
    if manifest_sha != expected_manifest:
        preflight_error = "CANDIDATE_MANIFEST_SHA256_MISMATCH"
    elif source_sha is None:
        preflight_error = "PRODUCER_SOURCE_MISSING"
    elif not args.candidate_app_root.is_dir():
        preflight_error = "CANDIDATE_APP_ROOT_MISSING"

    started_at = utc_now()
    started_monotonic = time.monotonic()
    process = None
    stdout_total = stdout_sha = stderr_total = stderr_sha = 0
    stdout_truncated = stderr_truncated = False
    launch_error = None
    with stdout_path.open("xb") as stdout_file, stderr_path.open("xb") as stderr_file:
        if preflight_error:
            stdout_file.flush(); os.fsync(stdout_file.fileno())
            stderr_file.flush(); os.fsync(stderr_file.fileno())
            return_code = 78
        else:
            try:
                process = subprocess.Popen(
                    command, cwd=args.candidate_app_root, env=os.environ.copy(),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                assert process.stdout is not None and process.stderr is not None
                # Drain both streams concurrently so a full pipe cannot deadlock the producer.
                import threading
                results: dict[str, tuple[int, str, bool]] = {}
                def drain(name: str, stream: BinaryIO, destination: BinaryIO) -> None:
                    results[name] = copy_capped(stream, destination, args.max_stream_bytes)
                out_thread = threading.Thread(target=drain, args=("stdout", process.stdout, stdout_file), daemon=True)
                err_thread = threading.Thread(target=drain, args=("stderr", process.stderr, stderr_file), daemon=True)
                out_thread.start(); err_thread.start()
                return_code = process.wait()
                out_thread.join(); err_thread.join()
                stdout_total, stdout_sha, stdout_truncated = results["stdout"]
                stderr_total, stderr_sha, stderr_truncated = results["stderr"]
            except OSError as exc:
                launch_error = f"{type(exc).__name__}: {exc}"
                return_code = 127
                if process and process.poll() is None:
                    process.kill(); process.wait()
        if not stdout_sha:
            stdout_sha = hashlib.sha256(b"").hexdigest()
        if not stderr_sha:
            stderr_sha = hashlib.sha256(b"").hexdigest()

    finished_at = utc_now()
    producer_result = parse_output(stdout_path, stdout_truncated)
    receipt = {
        "schema": "us_close_recovery_capture_receipt.v1",
        "run_id": run_id,
        "status": "PREFLIGHT_FAILED" if preflight_error else ("LAUNCH_FAILED" if launch_error else ("PRODUCER_EXIT_0" if return_code == 0 else "PRODUCER_NONZERO_EXIT")),
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "elapsed_seconds": round(time.monotonic() - started_monotonic, 6),
        "candidate_app_root": str(args.candidate_app_root),
        "candidate_manifest_path": str(args.candidate_manifest),
        "candidate_manifest_sha256_actual": manifest_sha,
        "candidate_manifest_sha256_expected": expected_manifest,
        "producer_source_path": str(source_path),
        "producer_source_sha256": source_sha,
        "command": command,
        "proxy_environment": {name: os.environ.get(name) for name in PROXY_ENV},
        "research_safety_flags": {name: os.environ.get(name) for name in ("RESEARCH_ONLY", "PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT")},
        "preflight_error": preflight_error,
        "launch_error": launch_error,
        "exit_code": return_code,
        "producer_result": producer_result,
        "stdout": {"path": stdout_path.name, "bytes_total": stdout_total, "sha256_full_stream": stdout_sha, "bytes_persisted": min(stdout_total, args.max_stream_bytes), "truncated": stdout_truncated},
        "stderr": {"path": stderr_path.name, "bytes_total": stderr_total, "sha256_full_stream": stderr_sha, "bytes_persisted": min(stderr_total, args.max_stream_bytes), "truncated": stderr_truncated},
        "receipt_sha256_path": receipt_sha_path.name,
    }
    payload = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with receipt_path.open("xb") as handle:
        handle.write(payload); handle.flush(); os.fsync(handle.fileno())
    receipt_hash = hashlib.sha256(payload).hexdigest()
    with receipt_sha_path.open("xb") as handle:
        handle.write(f"{receipt_hash}  {receipt_path.name}\n".encode("ascii")); handle.flush(); os.fsync(handle.fileno())
    print(json.dumps({"status": receipt["status"], "run_id": run_id, "receipt": str(receipt_path), "receipt_sha256": receipt_hash, "exit_code": return_code}, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
