from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

COLLECTOR = Path(__file__).with_name("collect_us_recovery_receipt.py")


def run_collector(tmp_path: Path, command: list[str], *, run_id: str | None, cap: int = 8, manifest_body: bytes = b"manifest", expected_sha: str | None = None, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    app = tmp_path / "app"
    app.mkdir(exist_ok=True)
    producer = app / "ops.py"
    producer.write_text("# synthetic producer source\n", encoding="utf-8")
    manifest = tmp_path / "release-manifest.json"
    manifest.write_bytes(manifest_body)
    expected = expected_sha or hashlib.sha256(manifest_body).hexdigest()
    receipt_dir = tmp_path / "receipts"
    command_args = [sys.executable, str(COLLECTOR), "--receipt-dir", str(receipt_dir),
         "--candidate-app-root", str(app), "--candidate-manifest", str(manifest),
         "--candidate-manifest-sha256", expected, "--producer-source", str(producer),
         "--max-stream-bytes", str(cap)]
    if run_id is not None:
        command_args.extend(["--run-id", run_id])
    command_args.extend(["--", *command])
    environment = {**os.environ,
            "HTTP_PROXY": "http://127.0.0.1:7897", "http_proxy": "http://127.0.0.1:7897",
            "HTTPS_PROXY": "http://127.0.0.1:7897", "https_proxy": "http://127.0.0.1:7897",
            "NO_PROXY": "127.0.0.1,localhost,::1", "no_proxy": "127.0.0.1,localhost,::1",
            "RESEARCH_ONLY": "1", "PRODUCTION_ALLOWED": "false",
            "BUY_GATE_UPDATED": "false", "ORDERS_SENT": "false"}
    if env_overrides:
        environment.update(env_overrides)
    return subprocess.run(
        command_args,
        text=True, capture_output=True, env=environment,
    )


def test_persists_bounded_streams_and_full_hash_on_nonzero_exit(tmp_path: Path) -> None:
    result = run_collector(tmp_path, [sys.executable, "-c", "import sys; print('abcdefghijk'); print('error-output', file=sys.stderr); raise SystemExit(7)"], run_id="failure-1", cap=5)
    assert result.returncode == 7
    metadata = json.loads(result.stdout)
    assert metadata["status"] == "PRODUCER_NONZERO_EXIT"
    receipt_path = Path(metadata["receipt"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["exit_code"] == 7
    assert receipt["stdout"]["truncated"] is True
    assert receipt["stdout"]["bytes_persisted"] == 5
    assert receipt["stdout"]["sha256_full_stream"] == hashlib.sha256(b"abcdefghijk\n").hexdigest()
    assert (receipt_path.parent / "stdout.bin").read_bytes() == b"abcde"
    assert receipt["stderr"]["truncated"] is True
    assert receipt["proxy_environment"]["https_proxy"] == "http://127.0.0.1:7897"
    assert receipt["research_safety_flags"]["ORDERS_SENT"] == "false"
    sidecar = receipt_path.with_name("receipt.sha256").read_text(encoding="ascii")
    assert hashlib.sha256(receipt_path.read_bytes()).hexdigest() in sidecar


def test_records_valid_json_and_uses_a_unique_run_directory(tmp_path: Path) -> None:
    first = run_collector(tmp_path, [sys.executable, "-c", "import json; print(json.dumps({'status':'READY','source_session_date':'20261015'}))"], run_id="ready-1", cap=500)
    second = run_collector(tmp_path, [sys.executable, "-c", "print('second')"], run_id="ready-2", cap=500)
    assert first.returncode == second.returncode == 0
    first_receipt = json.loads(json.loads(first.stdout)["receipt"] and Path(json.loads(first.stdout)["receipt"]).read_text())
    assert first_receipt["producer_result"] == {"status": "READY", "source_session_date": "20261015"}
    assert Path(json.loads(first.stdout)["receipt"]).parent != Path(json.loads(second.stdout)["receipt"]).parent


def test_manifest_mismatch_fails_closed_and_run_id_collision_does_not_overwrite(tmp_path: Path) -> None:
    result = run_collector(tmp_path, [sys.executable, "-c", "raise SystemExit('must not run')"], run_id="mismatch-1", expected_sha="0" * 64)
    assert result.returncode == 78
    mismatch = json.loads(Path(json.loads(result.stdout)["receipt"]).read_text())
    assert mismatch["status"] == "PREFLIGHT_FAILED"
    assert mismatch["preflight_error"] == "CANDIDATE_MANIFEST_SHA256_MISMATCH"
    receipt_path = Path(json.loads(result.stdout)["receipt"])
    before = receipt_path.read_bytes()
    collision = run_collector(tmp_path, [sys.executable, "-c", "print('must not overwrite')"], run_id="mismatch-1")
    assert collision.returncode == 73
    collision_meta = json.loads(collision.stdout)
    assert collision_meta["status"] == "RECEIPT_COLLISION"
    collision_receipt = Path(collision_meta["receipt"])
    collision_payload = json.loads(collision_receipt.read_text(encoding="utf-8"))
    assert collision_payload["producer_started"] is False
    assert collision_payload["preflight_error"] == "RECEIPT_RUN_ID_COLLISION"
    assert receipt_path.read_bytes() == before


def test_default_run_id_writes_success_and_failure_receipts_in_shanghai_timezone(tmp_path: Path) -> None:
    success = run_collector(
        tmp_path,
        [sys.executable, "-c", "import json; print(json.dumps({'status':'READY'}))"],
        run_id=None,
        cap=500,
        env_overrides={"TZ": "Asia/Shanghai"},
    )
    failure = run_collector(
        tmp_path,
        [sys.executable, "-c", "raise SystemExit(9)"],
        run_id=None,
        env_overrides={"TZ": "Asia/Shanghai"},
    )
    assert success.returncode == 0
    assert failure.returncode == 9

    success_meta = json.loads(success.stdout)
    failure_meta = json.loads(failure.stdout)
    success_receipt_path = Path(success_meta["receipt"])
    failure_receipt_path = Path(failure_meta["receipt"])
    success_receipt = json.loads(success_receipt_path.read_text(encoding="utf-8"))
    failure_receipt = json.loads(failure_receipt_path.read_text(encoding="utf-8"))

    for metadata, receipt, receipt_path in (
        (success_meta, success_receipt, success_receipt_path),
        (failure_meta, failure_receipt, failure_receipt_path),
    ):
        run_id = metadata["run_id"]
        assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", run_id)
        assert receipt["run_id"] == run_id
        assert receipt["started_at_utc"].endswith("Z")
        assert receipt["finished_at_utc"].endswith("Z")
        assert (receipt_path.parent / "receipt.sha256").is_file()
    assert success_receipt["status"] == "PRODUCER_EXIT_0"
    assert success_receipt["producer_result"] == {"status": "READY"}
    assert failure_receipt["status"] == "PRODUCER_NONZERO_EXIT"
    assert failure_receipt["exit_code"] == 9
    assert success_receipt_path.parent != failure_receipt_path.parent
