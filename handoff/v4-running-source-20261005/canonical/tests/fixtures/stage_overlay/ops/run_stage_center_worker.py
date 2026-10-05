"""Private child entry point used only by strict Stage dispatch."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def _read_request(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("STRICT_WORKER_REQUEST_MISSING")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != "stage_center.strict_worker_request.v1":
        raise ValueError("STRICT_WORKER_REQUEST_INVALID")
    return value


def _inside(root: Path, value: Any) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        raise ValueError("STRICT_WORKER_ROOT_NOT_ABSOLUTE")
    root = root.resolve()
    observed = path.resolve()
    if not observed.is_relative_to(root):
        raise ValueError("STRICT_WORKER_ROOT_ESCAPES_GENERATION")
    return observed


def supervise_child(
    command: Sequence[str],
    *,
    deadline_monotonic_ns: int,
    env: Mapping[str, str] | None = None,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    terminate_grace_seconds: float = 0.15,
) -> dict[str, Any]:
    """Run one child process group until its absolute deadline; always reap it."""
    started_ns = monotonic_ns()
    if started_ns >= deadline_monotonic_ns:
        return {"status": "CANNOT_CONFIRM", "timed_out": True, "reaped": True,
                "pid": None, "returncode": None, "started_monotonic_ns": started_ns,
                "finished_monotonic_ns": started_ns, "reason": "DEADLINE_BEFORE_CHILD_START"}
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            list(command), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=dict(env) if env is not None else None,
            start_new_session=True,
        )
        remaining = max(0.0, (deadline_monotonic_ns - monotonic_ns()) / 1_000_000_000)
        try:
            process.wait(timeout=remaining)
            finished = monotonic_ns()
            timed_out = finished > deadline_monotonic_ns
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=max(0.0, terminate_grace_seconds))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            finished = monotonic_ns()
        return {
            "status": "CANNOT_CONFIRM" if timed_out or process.returncode != 0 else "CHILD_EXITED",
            "timed_out": timed_out,
            "reaped": process.poll() is not None,
            "pid": process.pid,
            "returncode": process.returncode,
            "started_monotonic_ns": started_ns,
            "finished_monotonic_ns": finished,
            "reason": "CHILD_DEADLINE_EXCEEDED" if timed_out else None,
        }
    except OSError as error:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        return {"status": "CANNOT_CONFIRM", "timed_out": False,
                "reaped": process is None or process.poll() is not None,
                "pid": process.pid if process else None,
                "returncode": process.returncode if process else None,
                "started_monotonic_ns": started_ns,
                "finished_monotonic_ns": monotonic_ns(),
                "reason": f"CHILD_START_FAILED:{type(error).__name__}"}


def execute_strict_stage(
    *,
    app_root: Path | str,
    config: Mapping[str, Any],
    trade_date: str,
    stage_id: str,
    evaluated_at: Any,
    entry_monotonic_ns: int,
    deadline_monotonic_ns: int,
    supervisor_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the existing Stage runner in a private, killable child, then commit."""
    from stage_center.commit_store import (
        DEADLINE_BUDGET_NS,
        StageCommitStore,
        _read_object,
        _validate_date_stage,
        _write_json_durable,
    )
    from stage_center.contracts import SAFETY_FLAGS

    _validate_date_stage(trade_date, stage_id)
    if deadline_monotonic_ns != entry_monotonic_ns + DEADLINE_BUDGET_NS:
        return {"status": "CANNOT_CONFIRM", "trade_date": trade_date,
                "stage_id": stage_id, "blocked_layer": "STRICT_DEADLINE_CONTRACT",
                "cannot_confirm": ["ABSOLUTE_DEADLINE_CONTRACT_MISMATCH"], **SAFETY_FLAGS}
    receipt_root = Path(str(config["receipt_root"])).expanduser()
    generation_root = receipt_root / ".stage_generations" / trade_date / stage_id / uuid4().hex
    generation_root.mkdir(parents=True, exist_ok=False)
    child_config = dict(config)
    child_config.update({
        "raw_root": str(generation_root / "raw"),
        "selection_root": str(generation_root / "selection"),
        "receipt_root": str(generation_root / "receipts"),
    })
    result_path = generation_root / "worker_result.json"
    request_path = generation_root / "worker_request.json"
    _write_json_durable(request_path, {
        "schema_version": "stage_center.strict_worker_request.v1",
        "config": child_config,
        # Stage-8's immutable pre-capture is an input produced by the existing
        # separate 15:50 node. The child reads that snapshot from its source
        # root while all Stage raw/bundle/selection outputs stay private.
        "stage8_snapshot_source_root": str(config.get("raw_root") or ""),
        "trade_date": trade_date,
        "stage_id": stage_id,
        "evaluated_at": evaluated_at.isoformat(),
        "entry_monotonic_ns": entry_monotonic_ns,
        "deadline_monotonic_ns": deadline_monotonic_ns,
        "result_path": str(result_path),
        "generation_root": str(generation_root),
    })
    python_path = str(config.get("python_path") or "")
    worker_path = Path(app_root) / "ops" / "run_stage_center_worker.py"
    env = dict(os.environ)
    env.update({
        "V4_STAGE_PARENT_START_NS": str(entry_monotonic_ns),
        "V4_STAGE_DEADLINE_POLICY": "enforce",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(Path(app_root)) + os.pathsep + env.get("PYTHONPATH", ""),
    })
    child = supervise_child(
        [python_path, "-B", str(worker_path), str(request_path)],
        deadline_monotonic_ns=deadline_monotonic_ns,
        env=env,
    )
    if (
        child.get("timed_out") is True
        or child.get("reaped") is not True
        or child.get("returncode") != 0
        or time.monotonic_ns() > deadline_monotonic_ns
    ):
        return {
            "status": "CANNOT_CONFIRM", "trade_date": trade_date,
            "stage_id": stage_id, "blocked_layer": "STRICT_CHILD_EXECUTION",
            "deadline_status": "EXCEEDED" if child.get("timed_out") or time.monotonic_ns() > deadline_monotonic_ns else "NOT_VERIFIED",
            "private_generation": str(generation_root), "supervisor": child,
            "write_performed": False, "cannot_confirm": [child.get("reason") or "STRICT_CHILD_RESULT_UNAVAILABLE"],
            **SAFETY_FLAGS,
        }
    try:
        child_result = _read_object(result_path)
    except (OSError, ValueError, TypeError) as error:
        return {
            "status": "CANNOT_CONFIRM", "trade_date": trade_date,
            "stage_id": stage_id, "blocked_layer": "STRICT_CHILD_RESULT",
            "private_generation": str(generation_root), "supervisor": child,
            "write_performed": False, "cannot_confirm": [str(error)], **SAFETY_FLAGS,
        }
    committed = StageCommitStore(receipt_root).commit_generation(
        trade_date=trade_date,
        stage_id=stage_id,
        generation_root=generation_root,
        child_result=child_result,
        entry_monotonic_ns=entry_monotonic_ns,
        deadline_monotonic_ns=deadline_monotonic_ns,
        supervisor={**dict(supervisor_metadata or {}), **child},
    )
    if committed.get("status") not in {"READY", "READY_EMPTY"}:
        return {
            **dict(child_result), "status": "CANNOT_CONFIRM",
            "trade_date": trade_date, "stage_id": stage_id,
            "blocked_layer": "STRICT_COMMIT_OR_TERMINAL_WITNESS",
            "deadline_status": "EXCEEDED" if committed.get("reason") == "END_TO_END_5S_EXCEEDED" else "NOT_VERIFIED",
            "private_generation": str(generation_root), "supervisor": child,
            "commit": committed, "write_performed": False,
            **SAFETY_FLAGS,
        }
    return {
        **dict(child_result),
        "status": committed["status"],
        "stage_id": stage_id,
        "node_id": stage_id,
        "private_generation": str(generation_root),
        "supervisor": child,
        "transaction_id": committed["transaction_id"],
        "commit_receipt_sha256": committed["commit_receipt_sha256"],
        "commit_receipt_path": committed["commit_receipt_path"],
        "witness_path": committed["witness_path"],
        "terminal_monotonic_ns": committed["terminal_monotonic_ns"],
        "elapsed_ns": committed["elapsed_ns"],
        "deadline_verified": True,
        "write_performed": True,
        **SAFETY_FLAGS,
    }


def _stage8_snapshot_source_root(
    runner: Any,
    stage_id: str,
    trade_date: str,
    evaluated_at: datetime,
    *,
    source_root: Path,
    private_root: Path,
) -> tuple[Path, list[dict[str, Any]]]:
    """Reuse a prior immutable capture or retry it inside the supervised child."""
    if stage_id != "STAGE_1545_1555":
        return source_root, []
    if not source_root.is_absolute() or not private_root.is_absolute():
        raise ValueError("STRICT_STAGE8_SNAPSHOT_SOURCE_ROOT_INVALID")
    source_snapshot = (
        source_root / ".hk_active_snapshots" / trade_date / stage_id / "snapshot.json"
    )
    if source_snapshot.is_file() or evaluated_at > datetime.strptime(
        f"{trade_date} 15:55:00", "%Y%m%d %H:%M:%S"
    ).replace(tzinfo=evaluated_at.tzinfo):
        return source_root, []
    # The existing last-window retry used to run in the parent before strict
    # dispatch. Keep that behavior inside the killable process and private
    # generation so it shares the Stage deadline and cannot publish a late
    # shared snapshot.
    captures = list(runner._prepare_hk_active_snapshots(
        trade_date, evaluated_at, stage_id=stage_id
    ))
    return private_root, captures


def _bind_stage8_snapshot_source(runner: Any, stage_id: str, snapshot_root: Path) -> None:
    """Bind the immutable Stage-8 source without redirecting private outputs."""
    if stage_id != "STAGE_1545_1555":
        return
    if not snapshot_root.is_absolute():
        raise ValueError("STRICT_STAGE8_SNAPSHOT_SOURCE_ROOT_INVALID")
    from stage_center.hk_stage8 import production_natural_collectors

    runner.collectors.update(production_natural_collectors(snapshot_root=snapshot_root))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        return 2
    request_path = Path(args[0]).expanduser()
    try:
        request = _read_request(request_path)
        generation = Path(str(request.get("generation_root") or "")).expanduser().resolve()
        config = request.get("config")
        if not isinstance(config, dict):
            raise ValueError("STRICT_WORKER_CONFIG_INVALID")
        for key in ("raw_root", "selection_root", "receipt_root"):
            config[key] = str(_inside(generation, config.get(key)))
        result_path = _inside(generation, request.get("result_path"))
        trade_date = str(request.get("trade_date") or "")
        stage_id = str(request.get("stage_id") or "")
        evaluated_at = datetime.fromisoformat(str(request.get("evaluated_at") or ""))
        entry_ns = int(request.get("entry_monotonic_ns"))
        deadline_ns = int(request.get("deadline_monotonic_ns"))
        if deadline_ns != entry_ns + 5_000_000_000 or time.monotonic_ns() >= deadline_ns:
            raise ValueError("STRICT_WORKER_DEADLINE_INVALID")

        # Preserve the existing runner's source resolver and source_read_lease;
        # only the three output roots differ, and all three are private.
        from ops.run_stage_center_nodes import _build_runner
        from stage_center import end_to_end_deadline
        from stage_center.contracts import SAFETY_FLAGS

        end_to_end_deadline.install(time.monotonic_ns(), time.time_ns())
        runner = _build_runner(config)
        snapshot_source = Path(
            str(request.get("stage8_snapshot_source_root") or "")
        ).expanduser()
        snapshot_root, pre_captures = _stage8_snapshot_source_root(
            runner,
            stage_id,
            trade_date,
            evaluated_at,
            source_root=snapshot_source,
            private_root=Path(config["raw_root"]),
        )
        _bind_stage8_snapshot_source(runner, stage_id, snapshot_root)
        decision = next(
            item for item in runner.due_decisions(
                trade_date, evaluated_at, historical_backfill=False
            ) if item.stage_id == stage_id
        )
        result = dict(runner.run_one_for_supervisor(decision))
        result.setdefault("trade_date", trade_date)
        result.setdefault("stage_id", stage_id)
        result.setdefault("write_performed", False)
        result.setdefault("pre_captures", pre_captures)
        result.update(SAFETY_FLAGS)
        from stage_center.commit_store import _write_json_durable

        _write_json_durable(result_path, result)
        return 0
    except Exception as error:
        try:
            from stage_center.commit_store import _write_json_durable
            from stage_center.contracts import SAFETY_FLAGS

            result_path = Path(str(request.get("result_path") or "")) if "request" in locals() else None
            generation = Path(str(request.get("generation_root") or "")).resolve() if "request" in locals() else None
            if result_path is not None and generation is not None and result_path.resolve().is_relative_to(generation):
                _write_json_durable(result_path, {
                    "status": "CANNOT_CONFIRM",
                    "trade_date": request.get("trade_date"),
                    "stage_id": request.get("stage_id"),
                    "error": f"{type(error).__name__}:{error}",
                    "write_performed": False,
                    **SAFETY_FLAGS,
                })
                return 0
        except Exception:
            pass
        return 3


if __name__ == "__main__":  # pragma: no cover - subprocess entry point
    raise SystemExit(main())
