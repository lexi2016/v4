#!/usr/bin/env python3
"""Candidate-bound entrypoint for the independently reviewed scheduler cutover core."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

DOC_ROOT = Path(__file__).resolve().parent
BINDING_PATH = DOC_ROOT / "scheduler_cache_release_binding.json"
EXPECTED_BINDING_SHA256 = "bee081cef3b5327b90d738d3fca3ca6610cff59fd702afb91c18e57b37422334"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bind_core():
    if _sha(BINDING_PATH) != EXPECTED_BINDING_SHA256:
        raise RuntimeError("CACHE_RELEASE_BINDING_SHA_MISMATCH")
    binding = json.loads(BINDING_PATH.read_text(encoding="utf-8"))
    core_path = Path(binding["cutover_core_path"])
    if _sha(core_path) != binding["cutover_core_sha256"]:
        raise RuntimeError("REVIEWED_CUTOVER_CORE_SHA_MISMATCH")
    if Path(binding["preparation_receipt_path"]).resolve() != (DOC_ROOT / "scheduler_cache_release_preparation_receipt.json").resolve():
        raise RuntimeError("CACHE_RELEASE_PREPARATION_RECEIPT_PATH_MISMATCH")
    sys.path.insert(0, str(DOC_ROOT))
    import scheduler_release_cutover as core

    core_path_resolved = Path(core.__file__).resolve(strict=True)
    if core_path_resolved != core_path.resolve(strict=True):
        raise RuntimeError("REVIEWED_CUTOVER_CORE_IMPORT_PATH_MISMATCH")
    core.DOC_ROOT = DOC_ROOT
    core.PLIST = Path(binding["active_plist_path"])
    core.CANDIDATE = Path(binding["candidate_root"])
    core.STAGED_PLIST = Path(binding["candidate_staged_plist_path"])
    core.PREIMAGE = Path(binding["base_plist_preimage_path"])
    core.PREP_RECEIPT = Path(binding["preparation_receipt_path"])
    core.MANIFEST = Path(binding["candidate_manifest_path"])
    core.ACTIVE_CONFIG = Path(binding["manager_config_path"])
    core.ACTIVATION_RECEIPT = Path(binding["activation_receipt_path"])
    core.ROLLBACK_RECEIPT = Path(binding["rollback_receipt_path"])
    core.RUNTIME_REVIEW_SCHEMA = binding["runtime_review_schema"]
    core.WRITER_IDENTITY = binding["writer_identity"]
    return core


def main(mode: str) -> int:
    core = _bind_core()
    return core.main(mode)


if __name__ == "__main__":
    raise SystemExit("Use activate_scheduler_cache_release.py or rollback_scheduler_cache_release.py")
