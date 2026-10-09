#!/usr/bin/env python3
"""Verify an incoming GitHub commit-prefix bundle byte-for-byte."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

E = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_MAC_ACCEPTANCE_20261009")
manifest = json.loads((E / "incoming/github_tree_manifest.json").read_text(encoding="utf-8"))
package_root = E / "incoming/manager-three-channel-repair-20261009"
expected = {x["path"]: x for x in manifest["files"]}
actual_paths = sorted(p.relative_to(package_root).as_posix() for p in package_root.rglob("*") if p.is_file())
missing = sorted(set(expected) - set(actual_paths))
extra = sorted(set(actual_paths) - set(expected))
files = []
for rel in sorted(set(expected) & set(actual_paths)):
    data = (package_root / rel).read_bytes()
    git_sha = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
    sha256 = hashlib.sha256(data).hexdigest()
    e = expected[rel]
    files.append({"path": rel, "expected_size": e["size"], "actual_size": len(data),
                  "expected_git_blob_sha": e["git_blob_sha"], "actual_git_blob_sha": git_sha,
                  "sha256": sha256, "pass": len(data) == e["size"] and git_sha == e["git_blob_sha"]})
byte_count = sum(x["actual_size"] for x in files)
passed = not missing and not extra and all(x["pass"] for x in files)
receipt = {"schema_version": "github_bundle_receipt.v1", "repository": manifest["repository"],
           "commit": manifest["commit"], "prefix": manifest["prefix"], "expected_file_count": len(expected),
           "actual_file_count": len(actual_paths), "expected_byte_count": sum(x["size"] for x in expected.values()),
           "actual_byte_count": byte_count, "missing": missing, "extra": extra, "pass": passed, "files": files}
out = E / "evidence/GITHUB_BUNDLE_RECEIPT.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: receipt[k] for k in ("commit", "expected_file_count", "actual_file_count",
                                         "expected_byte_count", "actual_byte_count", "pass")},
                 ensure_ascii=False))
raise SystemExit(0 if passed else 1)
