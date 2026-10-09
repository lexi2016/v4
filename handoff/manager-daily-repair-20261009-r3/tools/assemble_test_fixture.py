#!/usr/bin/env python3
"""Reproduce the isolated test tree from exact repo objects plus this delivery.

The destination must not exist. No network fetch, runtime mutation, release
integration or source fallback is performed. This is a partial test closure,
not a full API/worker release image.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

# Keep the immutable, closed delivery inventory unchanged when loading the
# sibling verifier. Test execution writes only into the separate output tree.
sys.dont_write_bytecode = True
from verify_delivery import checked_path, read, verify_bundle


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--repository-root", type=Path, help="existing local clone with fixed commit objects")
    sources.add_argument("--snapshot-root", type=Path, help="exact downloaded files under their repository paths")
    args = parser.parse_args(argv)
    try:
        verify_bundle(args.bundle)
        output = args.output.absolute()
        checked_path(output.parent, output.name)
        if output.exists():
            raise ValueError("OUTPUT_MUST_NOT_EXIST")
        manifest_raw = read(args.bundle, "test_fixture_manifest.json")
        manifest = json.loads(manifest_raw)
        if manifest.get("schema_version") != "v4.manager_r3.test_fixture_sources.v1":
            raise ValueError("TEST_FIXTURE_SCHEMA_MISMATCH")
        files = manifest["files"]
        rels = [row["path"] for row in files]
        if not files or len(rels) != len(set(rels)) or len(files) > 1024:
            raise ValueError("TEST_FIXTURE_INVENTORY_INVALID")
        prepared = []
        for row in files:
            checked_path(output, row["path"])
            origin = row["origin"]
            if origin["kind"] == "delivery":
                raw = read(args.bundle, origin["path"])
            elif origin["kind"] == "repository":
                ref, source_path = origin["commit"], origin["path"]
                if not re.fullmatch(r"[0-9a-f]{40}", ref):
                    raise ValueError("FIXED_COMMIT_REQUIRED")
                checked_path(Path("."), source_path)
                if args.snapshot_root:
                    raw = read(args.snapshot_root, source_path)
                else:
                    result = subprocess.run(["git", "show", ref + ":" + source_path],
                        cwd=args.repository_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if result.returncode:
                        raise ValueError(f"FIXED_REPOSITORY_OBJECT_UNAVAILABLE:{source_path}")
                    raw = result.stdout
                git_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\x00" + raw).hexdigest()
                if git_sha != origin["git_blob_sha1"]:
                    raise ValueError(f"SOURCE_GIT_OBJECT_MISMATCH:{source_path}")
            else:
                raise ValueError("SOURCE_ORIGIN_INVALID")
            if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise ValueError(f"TEST_SOURCE_SHA_MISMATCH:{row['path']}")
            prepared.append((row["path"], raw))
        if sum(len(raw) for _, raw in prepared) > 64 * 1024 * 1024:
            raise ValueError("TEST_SOURCE_BUDGET_EXCEEDED")
        output.mkdir(parents=True, exist_ok=False)
        for rel, raw in prepared:
            path = checked_path(output, rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        receipt = {"status": "ASSEMBLED_TEST_FIXTURE_ONLY", "output": str(output),
            "files": len(prepared), "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "full_runtime_image": False, "integrated": "NOT_RUN", "deployed": "NOT_RUN"}
        (output / "test_fixture_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
