#!/usr/bin/env python3
"""Read-only R7 preflight or one authorized same-identity engineering resume.

This is an external entry point; it does not replace any of the seven pinned
scientific modules or immutable R7 control files.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys

ROOT = Path("/Users/lexi/Desktop/学习/因子工厂")
SRC = ROOT / "workspace/f5_breadth1_r3_frozen_input_20261011/src"
AUTH = ROOT / (
    "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011/"
    "receipts/r7_recovery_06/control_resume/R7_RECOVERY_06_RESUME_AUTHORIZATION_V3.json"
)
AUTH_SHA = "0672916a2cd60dafccc35e52f2bab21e3b27f9be2b5948da96e8b2edef262cd9"
PYTHON_SHA = "95fb891ec36d4022bdf62172f9d3c757fb3c7b1669a274cacc87fe261a535b7e"
SOURCE = {
    "__init__.py": "14cd4f13adeed7d5c8730560f6fca0b3f360ae78c6a2a8e7ae8a1c40ad8bf764",
    "f5_breadth1_budget.py": "fca2feceeb829b16a80dd54b87c224e2cb2a50a4a1ef4e1546734e53e454746d",
    "f5_breadth1_core.py": "967cd391d435d82dca11a53a1475af3c2caed990aff17143293f7174b5c187a5",
    "f5_breadth1_evaluate.py": "355ae6ebf149a807d2aed1dc797a0f0fb874e2b40c40ae8066f7e7862e274c36",
    "f5_breadth1_inputs.py": "215a528d89a718cda2f3f8c7a9e1275b637425dc23e32da11233cb30b819a742",
    "f5_breadth1_worker.py": "08b20a81d40bd25e24fa6ed282c08fceed31396ad619d3cb8189ef20a366edca",
    "run_f5_breadth1.py": "5e4b7a782d6b76b606ac312767203c1f56f92dd0ef4d5cfa3218666b8acbef25",
}


class GateError(RuntimeError):
    pass


def _pin(path: Path, expected: str, cap: int = 16 * 1024 * 1024) -> None:
    if not path.is_absolute():
        raise GateError("NON_ABSOLUTE_PINNED_PATH")
    try:
        ancestors = path.relative_to(ROOT).parts
    except ValueError:
        # Only the resolved Python executable is permitted outside ROOT.
        ancestors = () if path == Path(sys.executable).resolve() else None
    if ancestors is None:
        raise GateError("PINNED_PATH_OUTSIDE_PROJECT")
    cursor = ROOT
    for piece in ancestors:
        cursor = cursor / piece
        if cursor.is_symlink():
            raise GateError("PINNED_ANCESTOR_SYMLINK")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > cap:
        raise GateError("PINNED_FILE_MISSING_SYMLINK_OR_OVERSIZED")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise GateError(f"PINNED_SHA_MISMATCH:{path.name}")


def _runner():
    if sys.version_info[:3] != (3, 13, 12):
        raise GateError("LOCKED_PYTHON_VERSION_MISMATCH")
    _pin(Path(sys.executable).resolve(), PYTHON_SHA, cap=80 * 1024 * 1024)
    for name, digest in SOURCE.items():
        _pin(SRC / name, digest)
    _pin(AUTH, AUTH_SHA)
    if "run_f5_breadth1" in sys.modules:
        raise GateError("RUNNER_ALREADY_IMPORTED")
    sys.path.insert(0, str(SRC))
    runner = importlib.import_module("run_f5_breadth1")
    if Path(runner.__file__).absolute() != (SRC / "run_f5_breadth1.py").absolute():
        raise GateError("WRONG_RUNNER_MODULE")
    if runner._r7_chain_paths()["resume_authorization"] != AUTH:
        raise GateError("WRONG_RESUME_AUTH_PATH")
    return runner


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--target-free-preflight", action="store_true")
    group.add_argument("--registered-r7-resume", action="store_true")
    args = ap.parse_args(argv)
    try:
        runner = _runner()
        if args.target_free_preflight:
            record = runner._preflight_registered_r7_resume(AUTH, AUTH_SHA)
            from registry_adapter import OfficialRegistryAdapter
            if type(record["official"]) is not OfficialRegistryAdapter:
                raise GateError("NOT_THE_REAL_OFFICIAL_ADAPTER")
            result = {
                "schema": "ISSUE36_R7_TARGET_FREE_REAL_ADAPTER_PREFLIGHT_V1",
                "status": "PASS_TARGET_FREE_R7_RESUME_PREFLIGHT",
                "original_execution_id": record["resume_claim"].execution_id,
                "original_action_key": record["resume_claim"].action_key,
                "original_r7_debit": 1,
                "new_r7_debit": 0,
                "original_start_event_sha256": record["resume_start_event"]["event_sha256"],
                "original_failed_terminal_event_sha256": record["resume_failure_terminal_event"]["event_sha256"],
                "resume_contract_sha256": record["contract_sha256"],
                "resume_pending_binding_sha256": record["pending_binding_sha256"],
                "resume_read_release_sha256": record["resume_release"].expected_sha256,
                "official_adapter_class": "OfficialRegistryAdapter",
                "official_full_registry_read_and_validation": True,
                "target_reads": 0, "registry_writes": 0, "fit": 0, "predict": 0,
                "model_load": 0, "truth_decode": 0,
                "real_chain_executed": False,
            }
        else:
            result = runner.run_registered_real_chain(
                resume_authorization_path=AUTH,
                resume_authorization_sha256=AUTH_SHA,
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if args.target_free_preflight or result.get("status") in {
            "DIRECTION_ONLY", "NO_BREAKTHROUGH"
        } else 2
    except BaseException as exc:
        print(json.dumps({
            "schema": "ISSUE36_R7_ENTRY_ERROR_V1",
            "status": ("CANNOT_CONFIRM_TARGET_FREE_PREFLIGHT" if args.target_free_preflight
                       else "CANNOT_CONFIRM_R7_RESUME"),
            "error_type": type(exc).__name__, "error": str(exc),
            "no_refund": True, "no_automatic_retry": True,
            "target_reads": 0 if args.target_free_preflight else None,
            "fit": 0 if args.target_free_preflight else None,
            "predict": 0 if args.target_free_preflight else None,
            "truth_decode": 0 if args.target_free_preflight else None,
        }, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
