import hashlib
import importlib
import inspect
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

candidate = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_HK_STAGE_RECOVERY_20261003/"
    "issue23_runner_only_r2/stage_r1_binding_candidate"
).resolve()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


runner = importlib.import_module("stage_center.runner")
tick_planning = importlib.import_module("stage_center._runner_parts.tick_planning")
slot_execution = importlib.import_module("stage_center._runner_parts.slot_execution")
repros = []
for name, operation in (
    (
        "candidate StageCenterRunner.tick wrapper with historical_markets defaulting to None",
        lambda: runner.StageCenterRunner.tick(
            object(), "20261002", datetime(2026, 10, 2, 9, 25),
            stage_id="STAGE_0925",
        ),
    ),
    (
        "candidate StageCenterRunner._run_one wrapper with historical_markets defaulting to None",
        lambda: runner.StageCenterRunner._run_one(object(), None),
    ),
):
    try:
        operation()
        repros.append({"operation": name, "result": "NO_ERROR"})
    except Exception as error:
        repros.append(
            {
                "operation": name,
                "result": "ERROR",
                "error_type": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
            }
        )

modules = {
    "runner": Path(runner.__file__).resolve(),
    "tick_planning": Path(tick_planning.__file__).resolve(),
    "slot_execution": Path(slot_execution.__file__).resolve(),
}
print(
    json.dumps(
        {
            "python": sys.executable,
            "python_version": sys.version,
            "cwd": str(Path.cwd()),
            "candidate_module_paths": {
                name: {
                    "path": str(path),
                    "sha256": sha(path),
                    "inside_candidate": str(candidate) in str(path),
                }
                for name, path in modules.items()
            },
            "signatures": {
                "candidate_tick_wrapper": str(inspect.signature(runner.StageCenterRunner.tick)),
                "candidate_run_one_wrapper": str(
                    inspect.signature(runner.StageCenterRunner._run_one)
                ),
                "R1_tick_helper": str(
                    inspect.signature(tick_planning._StageCenterRunner_tick_body)
                ),
                "R1_slot_helper": str(
                    inspect.signature(slot_execution._StageCenterRunner__run_one_body)
                ),
            },
            "reproductions": repros,
            "service_or_collection_invoked": False,
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
)
