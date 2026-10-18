#!/usr/bin/env python3
"""Prepare local source fixtures from an explicit baseline and fixed public commit.

This script writes only to the caller-selected output directory. It does not
fetch from the network and does not create blinded payloads, assignments, or an
oracle. The fixed commit must already exist in the supplied repository clone.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess


FIXED_COMMIT = "6c32c0e18f7d7ae83fef8257dc35087695b35018"
FIXED_SOURCE_SHA256 = "5dedf912a9cc8b41646a5cfb0133ded4dbaa0168aae74157e75e4498cd1fd915"
FIXED_TESTS_SHA256 = "27fb218b81427ef5904213d7c1951dd9004bf00693537b4f8d7d6154778eead9"
BASELINE_SOURCE_SHA256 = "727a3f6cfcef626d6cf482eebf9e8d66418fcbe9817ae2e1dd1943c88e8384e0"
BASELINE_TESTS_SHA256 = "8c3012d0e1d5cb2d6816a8afcf2bb922fa9bef97935f755477bbfe41f4a85a6d"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def remote_file(repo: Path, path: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(repo), "show", f"{FIXED_COMMIT}:{path}"],
        stderr=subprocess.STDOUT,
    )


def reconstruct_complete_enumeration_guard(fixed_source: bytes) -> bytes:
    text = fixed_source.decode("utf-8")
    tree = ast.parse(text)
    target = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "process_pdf_batch"
    )
    guards = []
    for node in ast.walk(target):
        if not isinstance(node, ast.If):
            continue
        if any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "_require_active_recovery_claim"
            for child in ast.walk(node)
        ):
            guards.append(node)
    guards.sort(key=lambda node: node.lineno)
    if len(guards) != 2:
        raise ValueError(f"expected two claim guards; found {len(guards)}")

    lines = text.splitlines(keepends=True)
    guard = guards[1]
    del lines[guard.lineno - 1 : guard.end_lineno]
    reconstructed = "".join(lines).encode("utf-8")
    reconstructed_tree = ast.parse(reconstructed.decode("utf-8"))
    reconstructed_function = next(
        node for node in reconstructed_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "process_pdf_batch"
    )
    remaining = [
        node for node in ast.walk(reconstructed_function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_require_active_recovery_claim"
    ]
    if len(remaining) != 1:
        raise ValueError(f"expected one retained claim guard; found {len(remaining)}")
    return reconstructed


def write_variant(root: Path, source: bytes, tests: bytes) -> None:
    source_path = root / "infrastructure/zsxq_pdf_ingestion.py"
    tests_path = root / "tests/test_zsxq_pdf_ingestion.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    tests_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(source)
    tests_path.write_bytes(tests)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="local Git clone containing the fixed commit")
    parser.add_argument("--baseline-source", type=Path, required=True, help="explicit baseline source file")
    parser.add_argument("--baseline-tests", type=Path, required=True, help="explicit baseline test file")
    parser.add_argument("--output-dir", type=Path, required=True, help="new directory for local reference fixtures")
    args = parser.parse_args()

    repo = args.repo.resolve()
    subprocess.check_call(["git", "-C", str(repo), "cat-file", "-e", f"{FIXED_COMMIT}^{{commit}}"])
    baseline_source = args.baseline_source.read_bytes()
    baseline_tests = args.baseline_tests.read_bytes()
    fixed_source = remote_file(repo, "infrastructure/zsxq_pdf_ingestion.py")
    fixed_tests = remote_file(repo, "tests/test_zsxq_pdf_ingestion.py")
    checks = {
        "baseline source": (sha(baseline_source), BASELINE_SOURCE_SHA256),
        "baseline tests": (sha(baseline_tests), BASELINE_TESTS_SHA256),
        "fixed source": (sha(fixed_source), FIXED_SOURCE_SHA256),
        "fixed tests": (sha(fixed_tests), FIXED_TESTS_SHA256),
    }
    mismatches = [f"{name}: {actual} != {expected}" for name, (actual, expected) in checks.items() if actual != expected]
    if mismatches:
        raise ValueError("source identity mismatch: " + "; ".join(mismatches))

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    reference = output / "reference"
    reconstructed = reconstruct_complete_enumeration_guard(fixed_source)
    write_variant(reference / "baseline", baseline_source, baseline_tests)
    write_variant(reference / "fixed", fixed_source, fixed_tests)
    write_variant(reference / "reconstructed_defect", reconstructed, fixed_tests)

    print(json.dumps({
        "fixed_commit": FIXED_COMMIT,
        "baseline_source_sha256": sha(baseline_source),
        "baseline_tests_sha256": sha(baseline_tests),
        "fixed_source_sha256": sha(fixed_source),
        "fixed_tests_sha256": sha(fixed_tests),
        "reconstructed_source_sha256": sha(reconstructed),
        "output_dir": str(output),
        "oracle_or_blinded_payloads_written": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
