#!/usr/bin/env python3
"""Check frozen source bytes and apply/reverse every candidate patch in temp dirs.

This verifies handoff integrity. It performs no installation, service or data action.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent
BASE = ROOT / "test_support/frozen_repo/handoff/stage-selection-issues-20261008/source"


def identity(path: Path) -> dict:
    data = path.read_bytes()
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob_sha1": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def entries() -> list[dict]:
    batches = []
    auction = load("auction/CHANGE_MANIFEST.json")
    for owner in ("canonical", "active_stage_reference"):
        rows = []
        for item in auction["changes"]:
            if item["source_owner"] != owner:
                continue
            rows.append({
                "target": item["relative_path"],
                "before": BASE / item["before_package_path"].removeprefix("source/"),
                "after": ROOT / "auction" / item["after_path"],
                "before_sha256": item["before_sha256"],
                "after_sha256": item["after_sha256"],
            })
        batches.append({"name": "auction_" + owner,
                        "patch": ROOT / f"auction/patches/{owner}.patch", "rows": rows})
    hk_rows = []
    for item in load("hk/SHA_MAPPING.json")["changes"]:
        owner_path = Path(item["owner"]) / item["source_relative_path"]
        hk_rows.append({
            "target": item["source_relative_path"],
            "before": BASE / owner_path,
            "after": ROOT / "hk/after" / owner_path,
            "before_sha256": item["before_sha256"],
            "after_sha256": item["after_sha256"],
        })
    batches.append({"name": "hk_active_producer", "patch": ROOT / "hk/patches/active_producer_reference.patch", "rows": hk_rows})
    release_rows = []
    for item in load("release/RELEASE_SHA256_MANIFEST.json")["files"]:
        release_rows.append({
            "target": item["path"],
            "before": BASE / item["path"].removeprefix("source/") if item["before_sha256"] else None,
            "after": ROOT / "release" / item["path"],
            "before_sha256": item["before_sha256"],
            "after_sha256": item["after_sha256"],
        })
    batches.append({"name": "release_complete", "patch": ROOT / "release/release_p1.patch", "rows": release_rows})
    return batches


def run() -> dict:
    receipt = {"scope": "SOURCE_PATCH_INTEGRITY_ONLY", "baseline_commit": "00524e9050fe212f87911b56eea1c2db719dd94b",
               "frozen_source_checks": [], "patch_roundtrips": [], "passed": False}
    for item in load("evidence/SOURCE_MANIFEST.json")["files"]:
        actual = identity(BASE / item["path"].removeprefix("source/"))
        expected = {key: item[key] for key in actual}
        if actual != expected:
            raise RuntimeError(f"Frozen source mismatch: {item['path']}")
        receipt["frozen_source_checks"].append({"path": item["path"], **actual, "passed": True})
    for batch in entries():
        record = {"name": batch["name"], "patch": str(batch["patch"].relative_to(ROOT)),
                  "patch_sha256": identity(batch["patch"])["sha256"], "commands": [], "files": []}
        with tempfile.TemporaryDirectory(prefix="v4_issue28_patch_") as directory:
            temp = Path(directory)
            for row in batch["rows"]:
                if row["before"] is not None:
                    if identity(row["before"])["sha256"] != row["before_sha256"]:
                        raise RuntimeError(f"Wrong preimage: {row['target']}")
                    destination = temp / row["target"]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(row["before"], destination)
                if identity(row["after"])["sha256"] != row["after_sha256"]:
                    raise RuntimeError(f"Wrong delivered after-image: {row['target']}")
            for flags in (("--check",), ()):
                command = ["git", "apply", *flags, str(batch["patch"])]
                result = subprocess.run(command, cwd=temp, text=True, capture_output=True, check=False)
                record["commands"].append({"operation": "forward", "flags": list(flags), "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
                if result.returncode:
                    raise RuntimeError(f"Forward patch failed: {batch['name']}: {result.stderr}")
            for row in batch["rows"]:
                if (temp / row["target"]).read_bytes() != row["after"].read_bytes():
                    raise RuntimeError(f"Applied patch differs: {row['target']}")
                record["files"].append({"path": row["target"], "before_sha256": row["before_sha256"],
                                        "after_sha256": row["after_sha256"], "forward_matches": True})
            for flags in (("--reverse", "--check"), ("--reverse",)):
                command = ["git", "apply", *flags, str(batch["patch"])]
                result = subprocess.run(command, cwd=temp, text=True, capture_output=True, check=False)
                record["commands"].append({"operation": "reverse", "flags": list(flags), "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
                if result.returncode:
                    raise RuntimeError(f"Reverse patch failed: {batch['name']}: {result.stderr}")
            for row, evidence in zip(batch["rows"], record["files"], strict=True):
                candidate = temp / row["target"]
                if row["before"] is None:
                    if candidate.exists() or candidate.is_symlink():
                        raise RuntimeError(f"New file survived reverse patch: {row['target']}")
                elif candidate.read_bytes() != row["before"].read_bytes():
                    raise RuntimeError(f"Reverse patch differs: {row['target']}")
                evidence["reverse_matches"] = True
        record["passed"] = True
        receipt["patch_roundtrips"].append(record)
    receipt["passed"] = True
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path, help="JSON output path; use a fresh output directory")
    args = parser.parse_args()
    report = run()
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.receipt.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({"passed": True, "frozen_sources": len(report["frozen_source_checks"]),
                      "patch_roundtrips": len(report["patch_roundtrips"]), "receipt": str(args.receipt)}, ensure_ascii=False))
