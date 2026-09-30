#!/usr/bin/env python3
"""Compare captured local source identities with the read-only GitHub trees."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


HANDOFF = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def add_local(index: dict[str, dict[str, Any]], row: dict[str, Any], kind: str) -> None:
    path = row.get("path") or row.get("handoff_path")
    if not path:
        return
    record = index.setdefault(str(path), {"path": str(path), "local_sources": []})
    record["local_sources"].append({"kind": kind, **row})


def map_remote_path(ref_name: str, remote_path: str) -> tuple[str, str]:
    """Return (logical path, mapping kind), retaining original refs elsewhere."""
    if ref_name == "stage_evidence14":
        prefix = "research/pr12-pr13-mac-evidence-20260930/"
        if remote_path.startswith(prefix):
            suffix = remote_path[len(prefix) :]
            if suffix == "PACK_RECEIPT.json":
                return "evidence/stage14/PACK_RECEIPT.json", "stage14_exact_evidence"
            if suffix.startswith("publish/"):
                return "evidence/stage14/" + suffix, "stage14_exact_evidence"
    if ref_name == "manager_issue8_r9":
        prefix = "research/manager-r9-consumer-r1-20260930/"
        if remote_path.startswith(prefix):
            relative = remote_path[len(prefix) :]
            for tree in ("baseline/", "candidate/"):
                if relative.startswith(tree):
                    return relative[len(tree) :], "manager_source_snapshot_" + tree.rstrip("/")
    if ref_name in {"manager_issue8_preflight", "manager_r3_preflight"}:
        evidence_prefix = "research/manager-r9-consumer-r1-20260930/r3_local_preflight_20260930/"
        package_prefix = "research/manager-r9-consumer-r1-20260930/r3_preflight_20260930/"
        if remote_path.startswith(evidence_prefix):
            suffix = remote_path[len(evidence_prefix) :]
            return "evidence/manager_issue8_r3_preflight/evidence/" + suffix, "manager_r3_local_evidence"
        if remote_path.startswith(package_prefix):
            suffix = remote_path[len(package_prefix) :]
            return "evidence/manager_issue8_r3_preflight/package/" + suffix, "manager_r3_package"
    return remote_path, "repository_path"


def main() -> None:
    inventory = read_json(HANDOFF / "source_inventory.json")
    baseline_doc = read_json(HANDOFF / "references/github_baselines.json")
    main_readback = read_json(HANDOFF / "references/github_main_readback.json")
    local: dict[str, dict[str, Any]] = {}

    for row in inventory.get("canonical_source_rows", []):
        add_local(local, row, "canonical")
    for row in inventory.get("test_source_rows", []):
        add_local(local, row, "test_source")
    for row in inventory.get("build_lock_rows", []):
        add_local(local, row, "build_lock")
    for row in inventory.get("test_dependency_rows", []):
        if row.get("copied"):
            add_local(local, row, "safe_test_dependency")
    for row in inventory.get("test_import_source_rows", []):
        if row.get("copied"):
            add_local(local, row, "test_import_source")
    for row in inventory.get("configured_release_rows", []):
        if row.get("status") == "copied":
            add_local(local, row, "configured_release")
    for row in inventory.get("stage14_exact_copy_rows", []):
        add_local(local, row, "stage14_evidence")
    manager_evidence_receipt = HANDOFF / "evidence/manager_issue8_r3_evidence_copy.json"
    if manager_evidence_receipt.is_file():
        for row in read_json(manager_evidence_receipt).get("copied_files", []):
            add_local(local, row, "manager_existing_evidence")

    comparisons: dict[str, dict[str, Any]] = {
        path: {**record, "github": {}}
        for path, record in local.items()
    }
    ref_summaries: dict[str, dict[str, Any]] = {}
    remote_file_rows: list[dict[str, Any]] = []

    for ref_name, ref in baseline_doc.get("refs", {}).items():
        files = ref.get("files", [])
        ref_summaries[ref_name] = {
            "commit": ref.get("commit"),
            "branch": ref.get("branch"),
            "tree_count": ref.get("tree_count"),
            "fetched_file_count": len(files),
            "truncated": bool(ref.get("truncated")),
        }
        for remote in files:
            remote_path = str(remote.get("path", ""))
            remote_sha = remote.get("sha")
            logical_path, mapping_kind = map_remote_path(ref_name, remote_path)
            local_record = comparisons.setdefault(
                logical_path,
                {"path": logical_path, "local_sources": [], "github": {}},
            )
            source_comparisons = [
                {
                    "kind": source.get("kind"),
                    "owner": source.get("owner"),
                    "status": source.get("status"),
                    "blob_sha1": source.get("git_blob_sha1"),
                    "match": source.get("git_blob_sha1") == remote_sha
                    if source.get("git_blob_sha1")
                    else None,
                }
                for source in local_record["local_sources"]
            ]
            identity_results = [row["match"] for row in source_comparisons if row["match"] is not None]
            all_match = all(identity_results) if identity_results else None
            local_record["github"].setdefault(ref_name, []).append({
                "commit": ref.get("commit"),
                "remote_path": remote_path,
                "mapping_kind": mapping_kind,
                "blob_sha1": remote_sha,
                "bytes": remote.get("size"),
                "local_blob_sha1_match": all_match,
                "local_source_comparisons": source_comparisons,
            })
            remote_file_rows.append(
                {
                    "ref": ref_name,
                    "commit": ref.get("commit"),
                    "remote_path": remote_path,
                    "logical_path": logical_path,
                    "mapping_kind": mapping_kind,
                    "blob_sha1": remote_sha,
                    "bytes": remote.get("size"),
                    "local_snapshot_present": bool(local_record["local_sources"]),
                    "local_blob_sha1_match": all_match,
                    "local_source_comparisons": source_comparisons,
                }
            )

    local_match_counts: dict[str, dict[str, int]] = {}
    for ref_name in ref_summaries:
        counts = Counter()
        for record in comparisons.values():
            ref_entries = record.get("github", {}).get(ref_name, [])
            if ref_entries:
                for ref_entry in ref_entries:
                    value = ref_entry.get("local_blob_sha1_match")
                    counts["match" if value is True else "conflict" if value is False else "no_local_identity"] += 1
            else:
                counts["no_remote_path"] += 1
        local_match_counts[ref_name] = dict(sorted(counts.items()))

    stage14_rows = [
        row
        for row in remote_file_rows
        if row["ref"] == "stage_evidence14" and row["mapping_kind"] == "stage14_exact_evidence"
    ]
    report = {
        "schema_version": "mac_source_handoff.github_baseline_comparison.v1",
        "repository": baseline_doc.get("repository"),
        "local_canonical_head": inventory.get("canonical_head"),
        "read_only_fetch": baseline_doc.get("read_only_fetch"),
        "reference_summary": ref_summaries,
        "github_main_readback_context": main_readback,
        "summary": {
            "compared_logical_path_count": len(comparisons),
            "remote_blob_rows": len(remote_file_rows),
            "local_identity_match_counts_by_ref": local_match_counts,
            "stage14_exact_remote_blob_count": len(stage14_rows),
            "stage14_exact_remote_blob_all_match": bool(stage14_rows)
            and all(row["local_blob_sha1_match"] is True for row in stage14_rows),
            "github_main_source_files_returned": ref_summaries.get("github_main", {}).get("fetched_file_count", 0),
        },
        "mapping_notes": [
            "Direct repository paths retain their exact GitHub path.",
            "Manager R9 baseline/candidate code paths map from the issue package's baseline/ or candidate/ subtree to the original repository-relative source path; original remote_path is retained.",
            "Stage evidence14 maps to the local evidence/stage14 copy; exact Git blob SHA1 is compared.",
            "A missing local identity is not a content conflict. A missing remote path is not treated as a match.",
            "Git blob SHA1 identifies bytes only; it does not establish a commit ancestry, build provenance, runtime load, or business acceptance.",
        ],
        "per_file": [comparisons[path] for path in sorted(comparisons)],
        "remote_files": sorted(remote_file_rows, key=lambda row: (row["ref"], row["remote_path"])),
    }
    output = HANDOFF / "references/github_baseline_comparison.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
