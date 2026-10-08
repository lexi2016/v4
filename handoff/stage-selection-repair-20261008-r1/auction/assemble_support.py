"""Reproduce the bounded Issue28 source harness without a live application.

The current handoff lacks facade/dependency closure. Pinned 20261005 facades
provide the real builder entry point, formula, immutable store and consumer.
The Stage namespace helper is absent; an explicitly recorded historic API
read_global helper supplies that single name-resolution seam. No collector,
scheduler, external data service or application startup is executed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


BUNDLE = Path(__file__).resolve().parent


def fingerprint(data: bytes) -> dict:
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob_sha1": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest(),
    }


def checked_read(path: Path, expected: dict) -> bytes:
    data = path.read_bytes()
    actual = fingerprint(data)
    assert all(actual[key] == expected[key] for key in actual), f"source drift: {path}"
    return data


def assemble(owner: str, phase: str, destination: Path, *, namespace_support=True) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    support = json.loads((BUNDLE / "SUPPLEMENT_MANIFEST.json").read_text())
    changes = json.loads((BUNDLE / "SOURCE_CHANGES.json").read_text())
    loaded = []

    def install(source: Path, relative: str, expected: dict, role: str) -> None:
        data = checked_read(source, expected)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        loaded.append({"source": str(source.relative_to(BUNDLE)), "target": relative,
                       "role": role, **fingerprint(data)})

    for entry in support["files"]:
        relative = entry["path"].removeprefix("deps/")
        if relative.startswith(("api_reference/", "apps/")):
            continue
        install(BUNDLE / entry["path"], relative, entry, entry["owner_role"])
    for entry in changes["files"]:
        if entry["owner"] != owner and entry["relative_path"] != "stage_center/_selection_parts/a_auction.py":
            continue
        source = BUNDLE / phase / "source" / entry["owner"] / entry["relative_path"]
        install(source, entry["relative_path"], entry[phase], f"Issue28 {entry['owner']} {phase}")
    if namespace_support:
        helper = next(item for item in support["files"] if item["path"].endswith("/_namespace.py"))
        for package in ("_selection_parts", "_live_collectors_parts"):
            install(BUNDLE / helper["path"], f"stage_center/{package}/_namespace.py", helper,
                    "TEST_NAMESPACE_SUBSTITUTION; actual Stage helper missing")
    (destination / "HARNESS_MANIFEST.json").write_text(json.dumps({
        "owner_variant": owner, "phase": phase,
        "scope": "FROZEN_SOURCE_IMPORTS_AND_PERSISTENCE_PLUS_ISOLATED_API_ROUTE",
        "full_current_owner_application": "NOT_RUN",
        "namespace_support": namespace_support, "files": loaded,
    }, indent=2) + "\n")
    return destination
