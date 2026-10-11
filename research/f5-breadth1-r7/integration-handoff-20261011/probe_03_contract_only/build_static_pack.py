#!/usr/bin/env python3
"""Build a fresh, read-only registered R7 preflight probe identity."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path("/Users/lexi/Desktop/学习/因子工厂")
REG = ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011/receipts/r7_recovery_05/registration"
SRC = ROOT / "workspace/f5_breadth1_r3_frozen_input_20261011/src"
BASE = ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011"
LOCKED = "/Users/lexi/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an/work/hk_spike_f5_v1/HK_SPIKE_F5_TRAIN_V1/.venv_locked/bin/python3.13"
ROUTE = "F5_PLUS64_BREADTH1_R7_ONE_PROCESS_LOCAL_VALIDATION_20261011"
EXECUTION = ROUTE + "_R7_RESUME_PREFLIGHT_READONLY_03"
PROBE_NAME = "run_r7_resume_readonly_preflight_probe_03.py"
REGISTRAR_NAME = "register_r7_resume_readonly_preflight_03.py"
CONTRACT_NAME = "R7_RESUME_READONLY_PREFLIGHT_03_CONTRACT.json"
BINDING_NAME = "R7_RESUME_READONLY_PREFLIGHT_03_BINDING.json"
START_NAME = "R7_RESUME_READONLY_PREFLIGHT_03_START_RECEIPT.json"
TERMINAL_NAME = "R7_RESUME_READONLY_PREFLIGHT_03_TERMINAL_RECEIPT.json"
COMMAND_NAME = "R7_RESUME_READONLY_PREFLIGHT_03_COMMAND_RECEIPT.json"
REVIEWER_OUTPUT_NAME = "R7_RESUME_READONLY_PREFLIGHT_03_REVIEWER_OUTPUT.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_exclusive(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(value)


def dump(path: Path, obj: object) -> None:
    write_exclusive(path, (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def main() -> None:
    paths = {
        "probe": REG / PROBE_NAME,
        "registrar": REG / REGISTRAR_NAME,
        "contract": REG / CONTRACT_NAME,
        "binding": REG / BINDING_NAME,
        "start": REG / START_NAME,
        "terminal": REG / TERMINAL_NAME,
        "command": REG / COMMAND_NAME,
        "reviewer_output": REG / REVIEWER_OUTPUT_NAME,
    }
    collisions = [str(p) for p in paths.values() if p.exists() or p.is_symlink()]
    if collisions:
        raise SystemExit("NO_OVERWRITE_COLLISION:" + ",".join(collisions))

    old_probe = (REG / "run_r7_resume_readonly_preflight_probe_02.py").read_text(encoding="utf-8")
    probe = old_probe
    probe = probe.replace("PREFLIGHT_02_CONTRACT.json", "PREFLIGHT_03_CONTRACT.json")
    probe = probe.replace("PREFLIGHT_02_BINDING.json", "PREFLIGHT_03_BINDING.json")
    probe = probe.replace("PREFLIGHT_READONLY_02", "PREFLIGHT_READONLY_03")
    probe = probe.replace('"BREADTH1_R7_RESUME_READONLY_PREFLIGHT_PROBE_V1"', '"BREADTH1_R7_RESUME_READONLY_PREFLIGHT_PROBE_V2"')
    probe = probe.replace("import sys\n", "import sys\nimport traceback\n")
    probe = probe.replace('"error": str(exc),\n', '"error": str(exc),\n            "traceback": traceback.format_exc()[-16000:],\n')
    if "traceback.format_exc()" not in probe or "READONLY_PREFLIGHT_03" not in probe:
        raise SystemExit("PROBE_03_TRANSFORM_ASSERTION_FAILED")
    write_exclusive(paths["probe"], probe.encode("utf-8"))

    old_registrar = (REG / "register_r7_resume_readonly_preflight_02.py").read_text(encoding="utf-8")
    registrar = old_registrar
    for old, new in (
        ("PREFLIGHT_02_CONTRACT.json", "PREFLIGHT_03_CONTRACT.json"),
        ("PREFLIGHT_02_BINDING.json", "PREFLIGHT_03_BINDING.json"),
        ("PREFLIGHT_02_START_RECEIPT.json", "PREFLIGHT_03_START_RECEIPT.json"),
        ("PREFLIGHT_READONLY_02", "PREFLIGHT_READONLY_03"),
        ("run_r7_resume_readonly_preflight_probe_02.py", PROBE_NAME),
        ("register_r7_resume_readonly_preflight_02.py", REGISTRAR_NAME),
        ("R7_RESUME_READONLY_PREFLIGHT_02", "R7_RESUME_READONLY_PREFLIGHT_03"),
    ):
        registrar = registrar.replace(old, new)
    registrar = registrar.replace(
        '"start_stage": "R7_RESUME_READONLY_PREFLIGHT_STARTED",',
        '"start_stage": "R7_RESUME_READONLY_PREFLIGHT_03_STARTED",',
    ).replace(
        '"terminal_stage": "R7_RESUME_READONLY_PREFLIGHT_TERMINAL",',
        '"terminal_stage": "R7_RESUME_READONLY_PREFLIGHT_03_TERMINAL",',
    ).replace(
        '"one_variable": "registered_readonly_r7_resume_control_preflight",',
        '"one_variable": "registered_readonly_r7_resume_control_preflight_03_traceback",',
    )
    write_exclusive(paths["registrar"], registrar.encode("utf-8"))

    source_map = {str(p.relative_to(ROOT)): sha(p) for p in sorted(SRC.glob("*.py"))}
    if source_map.get("workspace/f5_breadth1_r3_frozen_input_20261011/src/run_f5_breadth1.py") != "49b7d01ab6dff04ed5130a55466826804589569b2ccd13d698a7dfe8df61b673":
        raise SystemExit("RUNNER_SOURCE_CHANGED_FROM_PARENT_PIN")

    old_binding = json.loads((REG / "R7_RESUME_READONLY_PREFLIGHT_02_BINDING.json").read_text(encoding="utf-8"))
    controls = {
        key: {"path": entry["path"], "sha256": sha(Path(entry["path"]))}
        for key, entry in old_binding["r7_control_sha256"].items()
    }
    deps = {
        key: {"path": entry["path"], "sha256": sha(Path(entry["path"]))}
        for key, entry in old_binding["official_dependency_sha256"].items()
    }
    probe_sha = sha(paths["probe"])
    registrar_sha = sha(paths["registrar"])
    command = f"PYTHON={LOCKED} {LOCKED} -I -B {paths['probe'].resolve()}"
    contract = json.loads((REG / "R7_RESUME_READONLY_PREFLIGHT_02_CONTRACT.json").read_text(encoding="utf-8"))
    contract.update({
        "schema": "BREADTH1_R7_RESUME_READONLY_PREFLIGHT_CONTRACT_V2",
        "execution_id": EXECUTION,
        "goal": "Independently verify the current R7 resume control graph, preserved failed lifecycle, and duplicate-output refusal without target data or R7 action debit; include traceback if a guard fails.",
        "command": command,
        "probe_path": str(paths["probe"].resolve()),
        "probe_sha256": probe_sha,
        "registrar_path": str(paths["registrar"].resolve()),
        "registrar_sha256": registrar_sha,
        "expected_receipt_paths": {
            "start": str(paths["start"].resolve()),
            "terminal": str(paths["terminal"].resolve()),
            "command_receipt": str(paths["command"].resolve()),
            "reviewer_output": str(paths["reviewer_output"].resolve()),
        },
        "output_policy": "Probe writes no files and no registry events; Reviewer returns exact stdout JSON, stderr, exit code, and elapsed time. Writer stores immutable output and appends the registered zero-fit TERMINAL afterward. Failure output includes bounded traceback.",
        "pass_signal": "Reviewer probe exits 0 and returns PASS_READONLY_RESUME_PREFLIGHT_AND_DUPLICATE_REFUSAL; exact registered lifecycle terminalized as ENGINEERING_CANARY_ONLY with zero fit debit and zero target input reads.",
        "source_sha256": source_map,
        "r7_control_sha256": controls,
        "official_dependency_sha256": deps,
        "status": "NO_FIT_ENGINEERING_CANARY_ONLY",
        "target_data_file_read_budget": 0,
        "model_paths_opened": [],
        "truth_paths_opened": [],
        "fit_cap": 0,
        "predict_cap": 0,
        "truth_decode_cap": 0,
        "additional_r7_debit_authorized": 0,
    })
    dump(paths["contract"], contract)
    contract_sha = sha(paths["contract"])
    binding = old_binding
    binding.update({
        "schema": "BREADTH1_R7_RESUME_READONLY_PREFLIGHT_BINDING_V2",
        "status": "STATIC_IDENTITY_FROZEN_REVIEWER_EXECUTION_PENDING",
        "execution_id": EXECUTION,
        "contract_path": str(paths["contract"].resolve()),
        "contract_sha256": contract_sha,
        "probe_path": str(paths["probe"].resolve()),
        "probe_sha256": probe_sha,
        "registrar_path": str(paths["registrar"].resolve()),
        "registrar_sha256": registrar_sha,
        "exact_command": command,
        "source_sha256": source_map,
        "r7_control_sha256": controls,
        "official_dependency_sha256": deps,
    })
    binding["read_paths_allowlist"] = [
        str(paths["probe"].resolve()), str(paths["registrar"].resolve()),
        *[entry["path"] for entry in controls.values()],
        *[entry["path"] for entry in deps.values()],
        *[str(p.resolve()) for p in sorted(SRC.glob("*.py"))],
        str((REG / "R7_RESUME_READONLY_PREFLIGHT_03_CONTRACT.json").resolve()),
        str(paths["binding"].resolve()),
        str((ROOT / "contracts/EXPERIMENT_REGISTRY.jsonl").resolve()),
    ]
    binding["reads_by_probe"] = {
        "target_inputs": 0, "model": 0, "evaluation_truth": 0, "registry_writes": 0, "file_outputs": 0,
    }
    dump(paths["binding"], binding)

    contract["binding_path"] = str(paths["binding"].resolve())
    contract["binding_sha256"] = sha(paths["binding"])
    # The contract is included in its binding, so contract cannot embed the binding SHA.
    # Keep the path only, and re-write the hash-free form consistently.
    contract.pop("binding_sha256", None)
    dump_tmp = paths["contract"].with_suffix(".tmp")
    dump_tmp.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dump_tmp.replace(paths["contract"])
    contract_sha = sha(paths["contract"])
    binding["contract_sha256"] = contract_sha
    # Rewriting the binding changes its SHA only; the contract deliberately does not bind it.
    bind_tmp = paths["binding"].with_suffix(".tmp")
    bind_tmp.write_text(json.dumps(binding, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bind_tmp.replace(paths["binding"])

    print(json.dumps({
        "status": "PROBE_03_STATIC_PACK_BUILT",
        "source_map": source_map,
        "current_control_sha256": controls,
        "official_dependency_sha256": deps,
        "probe_sha256": sha(paths["probe"]),
        "registrar_sha256": sha(paths["registrar"]),
        "contract_sha256": sha(paths["contract"]),
        "binding_sha256": sha(paths["binding"]),
        "contract_binding_sha256": json.loads(paths["binding"].read_text(encoding="utf-8"))["contract_sha256"],
        "binding_contract_sha256": json.loads(paths["contract"].read_text(encoding="utf-8")).get("binding_sha256"),
        "output_paths_absent": all(not paths[k].exists() for k in ("start", "terminal", "command", "reviewer_output")),
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
