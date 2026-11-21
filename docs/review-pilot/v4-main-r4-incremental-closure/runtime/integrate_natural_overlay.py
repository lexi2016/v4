"""Integrate only the frozen natural/QFQ overlay into the isolated app copy."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil


TASK = Path(__file__).resolve().parent
RELEASE = TASK / "v4-main-r4-incremental-closure-20261122"
BASE = TASK.parents[1] / "v4_main_r4_review_remediation_20261121" / "runtime" / "v4-main-r4-review-remediation-20261121"
SOURCE_ROOT = TASK.parent / "natural" / "app"
OVERLAY_RECEIPT = TASK.parent / "natural" / "NATURAL_QFQ_DIRECTORY_TEST_RECEIPT.json"
ALLOWLIST = {
    "ops/qfq_directory_contract.py": {
        "before": None,
        "after": "3b5bf6c36369cdef983f8061087446d051c2f2f06c2489954dadb3d7d7c7d951",
    },
    "ops/research_storage_governance.py": {
        "before": "5e8fe6d05a0d6ea722e4e022d2cca22359ed0f8384fbf3670a3e28a18aa25fd2",
        "after": "2ff7ced3580210364143321e44221a99a66df0eca5a223eff277666b5b40a68e",
    },
    "infrastructure/scheduling/executor_registry_review.py": {
        "before": "cd5eee80baa4b23f773dd5b39553c1a8ae4007cb0558b5339053956d41d022e4",
        "after": "3402f3525d55387d79a0c7d6686f41d5fc07125f73ae6f414fc537b80c36cbda",
    },
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_mode(path: Path) -> str:
    return format(path.stat().st_mode & 0o777, "04o")


def main() -> None:
    manifest = json.loads((BASE / "release-manifest.json").read_bytes())
    baseline = {row["path"]: row for row in manifest["application_inventory"]["entries"]}
    changed = []
    for relative, expected in ALLOWLIST.items():
        source = SOURCE_ROOT / relative
        destination = RELEASE / "app" / relative
        if not source.is_file() or source.is_symlink() or sha(source) != expected["after"] or file_mode(source) != "0644":
            raise RuntimeError("NATURAL_SOURCE_SHA_MODE_MISMATCH:" + relative)
        if expected["before"] is None:
            if relative in baseline or destination.exists() or destination.is_symlink():
                raise RuntimeError("NATURAL_NEW_HELPER_PREIMAGE_CONFLICT")
        else:
            prior = baseline.get(relative)
            if prior is None or prior.get("sha256") != expected["before"] or sha(destination) != expected["before"]:
                raise RuntimeError("NATURAL_OVERLAY_PREIMAGE_MISMATCH:" + relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        os.chmod(destination, 0o644)
        if sha(destination) != expected["after"] or file_mode(destination) != "0644":
            raise RuntimeError("NATURAL_OVERLAY_COPIED_SHA_MODE_MISMATCH:" + relative)
        changed.append({"path": relative, "before_sha256": expected["before"],
                        "source_sha256": expected["after"], "candidate_sha256": sha(destination),
                        "mode": file_mode(destination)})
    upstream = json.loads(OVERLAY_RECEIPT.read_bytes())
    if upstream.get("status") not in {"PASS", "PASS_TARGETED_QFQ_DIRECTORY_CONTRACT"} and not str(upstream.get("status", "")).startswith("PASS"):
        raise RuntimeError("UPSTREAM_NATURAL_TEST_RECEIPT_NOT_PASS")
    receipt = {"schema": "v4.r4_incremental_natural_overlay_integration.v1",
               "status": "PASS_FROZEN_NATURAL_OVERLAY_INTEGRATED",
               "source_root": str(SOURCE_ROOT), "candidate_release_root": str(RELEASE),
               "source_test_receipt": str(OVERLAY_RECEIPT),
               "source_test_receipt_sha256": sha(OVERLAY_RECEIPT),
               "source_test_status": upstream.get("status"),
               "source_test_counts": {key: upstream[key] for key in ("passed", "failed", "skipped") if key in upstream},
               "changed_app_files": changed,
               "production_write": False, "scheduler_or_claim_called": False}
    (TASK / "NATURAL_OVERLAY_INTEGRATION_RECEIPT.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
