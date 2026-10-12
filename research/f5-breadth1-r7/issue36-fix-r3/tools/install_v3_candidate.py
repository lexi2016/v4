#!/usr/bin/env python3
"""Issue #36 V3 file installation; never imports research modules or opens target data.

Use --check before --apply. Each existing source must match the pinned original
SHA. New controls are created exclusively, old controls and failure receipts are
never overwritten. Installation itself does not authorize training.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path("/Users/lexi/Desktop/学习/因子工厂")
BATCH = ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011"
SRC = "workspace/f5_breadth1_r3_frozen_input_20261011/src/"
FILES = {
    SRC + "f5_breadth1_budget.py": ("after/" + SRC + "f5_breadth1_budget.py",
        "0746398c572ec070f96cfbb27826b3ae6ab5ae7a7839792dd01b0324ebf393cb",
        "fca2feceeb829b16a80dd54b87c224e2cb2a50a4a1ef4e1546734e53e454746d"),
    SRC + "f5_breadth1_inputs.py": ("after/" + SRC + "f5_breadth1_inputs.py",
        "86d7eb720469da17cebf2d05f06e5572dd0365b3e5d96efa6b1deeded5818383",
        "215a528d89a718cda2f3f8c7a9e1275b637425dc23e32da11233cb30b819a742"),
    SRC + "run_f5_breadth1.py": ("after/" + SRC + "run_f5_breadth1.py",
        "49b7d01ab6dff04ed5130a55466826804589569b2ccd13d698a7dfe8df61b673",
        "5e4b7a782d6b76b606ac312767203c1f56f92dd0ef4d5cfa3218666b8acbef25"),
}
NEW = {
    "controls/resume_v3/R7_RECOVERY_06_RESUME_CONTRACT_V3.json":
      ("receipts/r7_recovery_06/control_resume/R7_RECOVERY_06_RESUME_CONTRACT_V3.json",
       "7c158df66723be964945335a40355ef72b7b4f6574713a9177961c5fad9b9c0e"),
    "controls/resume_v3/PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_PENDING_BINDING_RESUME_03.json":
      ("bindings/PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_PENDING_BINDING_RESUME_03.json",
       "a27d5ac129a014b739bb05283579a4739d15610494d725a9ea652e9ff0b7aef7"),
    "controls/resume_v3/PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_READ_RELEASE_RESUME_03.json":
      ("bindings/PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_READ_RELEASE_RESUME_03.json",
       "ea4228111f2c010d5c74a455696e9dd288497d8c7646e0246c0c5fb08761925c"),
    "controls/resume_v3/R7_RECOVERY_06_RESUME_READ_PLAN_V3.json":
      ("receipts/r7_recovery_06/control_resume/R7_RECOVERY_06_RESUME_READ_PLAN_V3.json",
       "1c4efe4a5beb01ac5eaa65e873e544d322baa82deb8b198bb966dc199a987810"),
    "controls/resume_v3/R7_RECOVERY_06_RESUME_AUTHORIZATION_V3.json":
      ("receipts/r7_recovery_06/control_resume/R7_RECOVERY_06_RESUME_AUTHORIZATION_V3.json",
       "0672916a2cd60dafccc35e52f2bab21e3b27f9be2b5948da96e8b2edef262cd9"),
}
ORIGINAL_TERMINAL = BATCH / "receipts/r7_recovery_05/resume_invocation_02/PIPELINE_TERMINAL_RECEIPT.json"
ORIGINAL_TERMINAL_SHA = "254e63c23c0b9b11b2685725796b4ebcfcafc234fd1eb5b2d086f04e655e76bd"
ENTRY_SOURCE = "launcher/r7_resume_v3_launcher.py"
ENTRY_SHA = "6879dce51eee81adf194a021b9d50a8c23dc399a164be7e758b6d685003d6ba0"
ENTRY_DEST = ROOT / "handoffs/issue36-r7-v3/r7_resume_v3_launcher.py"
BACKUP_ROOT = ROOT / "handoffs/issue36-r7-v3/backups"
OUT_RUN = BATCH / "receipts/r7_recovery_06/resume_invocation_03"
OUT_BIND = BATCH / "bindings/PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_ADMITTED_BINDING_RESUME_03.json"


def digest(path: Path, maximum: int = 20 * 1024 * 1024) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError(f"UNSAFE_OR_MISSING_PINNED_FILE:{path}")
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check(root: Path) -> dict:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("BUNDLE_ROOT_MISSING_OR_SYMLINK")
    if not ROOT.is_dir() or not BATCH.is_dir():
        raise ValueError("FIXED_PROJECT_AND_BATCH_ROOT_REQUIRED")
    if OUT_RUN.exists() or OUT_RUN.is_symlink() or OUT_BIND.exists() or OUT_BIND.is_symlink():
        raise ValueError("RESUME03_PREVIOUSLY_STARTED_OR_BINDING_PRESENT")
    if digest(ORIGINAL_TERMINAL) != ORIGINAL_TERMINAL_SHA:
        raise ValueError("PRIOR_FAILED_INVOCATION_02_DRIFT")
    for rel, (supplied, old, new) in FILES.items():
        if digest(ROOT / rel) != old:
            raise ValueError(f"R7_CODE_ALREADY_CHANGED_OR_PARTIAL_INSTALL:{rel}")
        if digest(root / supplied) != new:
            raise ValueError(f"AFTER_SOURCE_BYTES_MISMATCH:{supplied}")
    for supplied, (rel, sha) in NEW.items():
        p = BATCH / rel
        if p.exists() or p.is_symlink():
            raise ValueError(f"V3_CONTROL_ALREADY_EXISTS_NO_OVERWRITE:{p}")
        if digest(root / supplied) != sha:
            raise ValueError(f"V3_CONTROL_SOURCE_SHA_MISMATCH:{supplied}")
    if ENTRY_DEST.exists() or ENTRY_DEST.is_symlink():
        raise ValueError("V3_LAUNCHER_ALREADY_EXISTS_NO_OVERWRITE")
    if digest(root / ENTRY_SOURCE) != ENTRY_SHA:
        raise ValueError("V3_LAUNCHER_SOURCE_SHA_MISMATCH")
    if BACKUP_ROOT.exists() or BACKUP_ROOT.is_symlink():
        raise ValueError("V3_BACKUP_ALREADY_EXISTS")
    return {"status": "READY_FOR_INSTALL_FILES_ONLY", "source_files": len(FILES),
            "new_controls": len(NEW), "original_r7_debit_preserved": 1,
            "model_training_authorized_by_this_check": False}


def write_exclusive(dst: Path, payload: bytes):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink():
        raise ValueError("DESTINATION_SYMLINK")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(dst, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        raise


def apply(root: Path):
    result = check(root)
    BACKUP_ROOT.mkdir(parents=True, exist_ok=False)
    # Never delete these backups. An interrupted install is not auto-retried.
    for rel in FILES:
        write_exclusive(BACKUP_ROOT / Path(rel).name, (ROOT / rel).read_bytes())
    for supplied, (rel, expected) in NEW.items():
        write_exclusive(BATCH / rel, (root / supplied).read_bytes())
        if digest(BATCH / rel) != expected:
            raise ValueError("V3_CONTROL_WRITE_READBACK_MISMATCH")
    write_exclusive(ENTRY_DEST, (root / ENTRY_SOURCE).read_bytes())
    if digest(ENTRY_DEST) != ENTRY_SHA:
        raise ValueError("V3_ENTRY_READBACK_MISMATCH")
    # Replacement is intentionally last, after immutable copies and backups.
    for rel, (supplied, before, after) in FILES.items():
        target = ROOT / rel
        if digest(target) != before:
            raise ValueError("SOURCE_DRIFT_DURING_INSTALL_STOP")
        tmp = target.with_name(target.name + ".issue36-v3.tmp")
        write_exclusive(tmp, (root / supplied).read_bytes())
        if digest(tmp) != after:
            raise ValueError("SOURCE_STAGED_SHA_MISMATCH")
        os.replace(tmp, target)
        if digest(target) != after:
            raise ValueError("SOURCE_POST_REPLACE_SHA_MISMATCH")
    return {"status": "INSTALLED_FILES_ONLY_NOT_TESTED", "source_files": 3,
            "new_controls": 5, "launcher_sha256": ENTRY_SHA,
            "official_registry_mutations": 0, "target_reads": 0,
            "fit": 0, "predict": 0, "truth_decode": 0,
            "next": "Run real Mac --target-free-preflight once, independently review before real resume."}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", type=Path, required=True,
                        help="Local downloaded issue36-fix-r3 folder with after/ controls/ launcher/")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        outcome = check(args.bundle_root) if args.check else apply(args.bundle_root)
        print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "STOP_INSTALL_NO_RETRY", "type": type(exc).__name__,
                          "error": str(exc), "quota_refunded": False}, ensure_ascii=False), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
