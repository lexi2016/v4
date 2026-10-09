#!/usr/bin/env python3
"""Verify file-byte identities and all six minimal patches in temporary roots."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

PACKAGE = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((PACKAGE / "SOURCE_MAP.json").read_text())
    checks, problems = [], []
    for role, group in manifest["roles"].items():
        for item in group["files"]:
            for label in ("before", "r1", "after"):
                path, expected = item[label + "_path"], item[label + "_sha256"]
                if path is not None and sha(PACKAGE / path) != expected:
                    problems.append(f"{role}:{label}:{item['relative_path']}:SHA_MISMATCH")
        for origin, patch_key in (("before", "restored_patch"), ("r1", "r1_patch")):
            patch = PACKAGE / group[patch_key]
            with tempfile.TemporaryDirectory(prefix="v4-stage-patch-") as name:
                root = Path(name)
                for item in group["files"]:
                    if item[origin + "_path"]:
                        target = root / item["relative_path"]
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes((PACKAGE / item[origin + "_path"]).read_bytes())
                commands = []
                for flags in (("--check",), (), ("--reverse", "--check"), ("--reverse",)):
                    process = subprocess.run(["git", "apply", *flags, str(patch)], cwd=root,
                                             capture_output=True, text=True)
                    commands.append({"flags": list(flags), "exit_code": process.returncode,
                                     "stderr": process.stderr})
                    if process.returncode:
                        problems.append(f"{role}:{origin}:PATCH_FAILED:{flags}")
                        break
                    if not flags:
                        for item in group["files"]:
                            if sha(root / item["relative_path"]) != item["after_sha256"]:
                                problems.append(f"{role}:{origin}:{item['relative_path']}:AFTER_DIFFERS")
                for item in group["files"]:
                    if sha(root / item["relative_path"]) != item[origin + "_sha256"]:
                        problems.append(f"{role}:{origin}:{item['relative_path']}:REVERSE_DIFFERS")
                checks.append({"role": role, "origin": origin, "patch": str(patch.relative_to(PACKAGE)),
                               "patch_sha256": sha(patch), "commands": commands})
    report = {"schema_version": "v4.stage.patch_roundtrip.v2",
              "checked_at": datetime.now(timezone.utc).isoformat(),
              "status": "PASS" if not problems else "FAIL", "checks": checks, "problems": problems,
              "source_map_sha256": sha(PACKAGE / "SOURCE_MAP.json"), "active_runtime_updated": False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "patches": len(checks), "problems": problems}, ensure_ascii=False))
    return 0 if not problems else 2


if __name__ == "__main__":
    raise SystemExit(main())
