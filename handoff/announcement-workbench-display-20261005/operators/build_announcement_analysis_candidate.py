#!/usr/bin/env python3
"""Build and dry-run the exact 2026-09-29 announcement analysis import.

This script is offline. It writes only the reviewable candidate and dry-run
receipt requested by --candidate-output and --receipt-output, after resolving
both destinations and rejecting any destination inside --state-root; it never
writes to --state-root or to a running release.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return value


def _within(path: Path, root: Path) -> bool:
    """Return whether a resolved output path is the state root or its child."""
    return path == root or root in path.parents


def _resolve_safe_outputs(candidate_output: Path, receipt_output: Path,
                          state_root: Path) -> tuple[Path, Path]:
    """Resolve and reject any dry-run output that can write into owner state."""
    candidate = candidate_output.expanduser().resolve()
    receipt = receipt_output.expanduser().resolve()
    for label, path in (("candidate", candidate), ("receipt", receipt)):
        if _within(path, state_root):
            raise ValueError(f"DRY_RUN_{label.upper()}_WITHIN_STATE_ROOT")
    if candidate == receipt:
        raise ValueError("DRY_RUN_OUTPUT_PATHS_MUST_DIFFER")
    return candidate, receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--sources-root", type=Path, required=True)
    parser.add_argument("--catalog-canary", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--candidate-output", type=Path, required=True)
    parser.add_argument("--receipt-output", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repo_root.resolve(strict=True)
    sources = args.sources_root.resolve(strict=True)
    state = args.state_root.resolve(strict=True)
    canary_path = args.catalog_canary.resolve(strict=True)
    # Resolve and guard both destinations before any mkdir/write. Path.resolve
    # follows existing symlink parents and leaf links, including relative paths.
    candidate_path, receipt_path = _resolve_safe_outputs(
        args.candidate_output, args.receipt_output, state)
    sys.path.insert(0, str(repo))
    from v4.manager_research.announcement_analysis import (
        EXPECTED_BODY_SHA256,
        EXPECTED_COUNTS,
        EXPECTED_INPUTS,
        EXPECTED_SEMANTIC_SHA256,
        build_product,
        product_path as analysis_product_path,
        validate_product,
    )
    from v4.manager_research.workspace_projection import digest

    input_files = {
        "semantic_catalog": "semantic_catalog_20260929_v2.json",
        "body_corpus": "body_corpus_20260929_v3.json",
        "short_additions": "semantic_short_additions_20260929.json",
        "long_additions": "semantic_long_additions_20260929.json",
        "pdf_derivative_index": "pdf_text_derivatives_20260929_v3_index.json",
    }
    raw_inputs: dict[str, dict[str, Any]] = {}
    descriptors: list[dict[str, Any]] = []
    for name, filename in input_files.items():
        path = sources / filename
        raw = path.read_bytes()
        value = load_json(path)
        actual_sha = hashlib.sha256(raw).hexdigest()
        expected = EXPECTED_INPUTS[name]
        if actual_sha != expected["sha256"]:
            raise ValueError(f"INPUT_SHA_MISMATCH:{name}")
        if name == "semantic_catalog":
            row_count = value.get("row_count")
        elif name == "body_corpus":
            row_count = value.get("article_count")
        else:
            rows = value.get("records", value.get("rows"))
            row_count = len(rows) if isinstance(rows, list) else None
        if row_count != expected["row_count"]:
            raise ValueError(f"INPUT_COUNT_MISMATCH:{name}")
        raw_inputs[name] = value
        descriptors.append({"name": name, "sha256": actual_sha, "row_count": row_count})

    semantic = raw_inputs["semantic_catalog"]
    body = raw_inputs["body_corpus"]
    derivative_index = raw_inputs["pdf_derivative_index"]
    derivative_rows = derivative_index.get("rows")
    if not isinstance(derivative_rows, list) or len(derivative_rows) != 22:
        raise ValueError("PDF_DERIVATIVE_INDEX_COUNT_INVALID")
    derivative_shas: dict[str, str] = {}
    derivative_root = sources / "pdf_text_derivatives_20260929_v3"
    for row in derivative_rows:
        if not isinstance(row, dict) or not isinstance(row.get("art_code"), str):
            raise ValueError("PDF_DERIVATIVE_ROW_INVALID")
        name = Path(str(row.get("derivative_path") or "")).name
        options = [sources / name, derivative_root / name]
        matches = [path for path in options if path.is_file() and file_sha(path) == row.get("derivative_sha256")]
        if not name or len(matches) != 1:
            raise ValueError("PDF_DERIVATIVE_SHA_MISMATCH")
        derivative_shas[row["art_code"]] = row["derivative_sha256"]
    if len(derivative_shas) != 22:
        raise ValueError("PDF_DERIVATIVE_ART_CODE_DUPLICATE")

    canary = load_json(canary_path)
    catalog = canary.get("catalog")
    if (canary.get("schema_version") != "v4.manager_research.eastmoney_hk_date_catalog_read.v1"
            or canary.get("target_trade_date") != "20260930"
            or canary.get("publication_date") != "2026-09-29"
            or canary.get("source_scope") != "EASTMONEY_HK_DATE_CATALOG"
            or canary.get("status") != "COMPLETE"
            or canary.get("readback_status") != "VERIFIED"
            or not isinstance(catalog, dict)):
        raise ValueError("CATALOG_CANARY_IDENTITY_INVALID")

    product = build_product(
        semantic,
        body,
        canary,
        semantic_sha256=EXPECTED_SEMANTIC_SHA256,
        body_sha256=EXPECTED_BODY_SHA256,
        verified_inputs=descriptors,
        pdf_derivative_sha256s=derivative_shas,
    )
    validate_product(product, target_trade_date="20260930",
                     publication_date="2026-09-29", catalog=catalog)
    encoded = json.dumps(product, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    if candidate_path.exists() and candidate_path.read_bytes() != encoded:
        raise FileExistsError("CANDIDATE_OUTPUT_EXISTS_WITH_DIFFERENT_CONTENT")
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    # Re-resolve after parent creation so a symlinked output directory cannot
    # redirect a previously checked path into the owner state root.
    candidate_path, receipt_path = _resolve_safe_outputs(candidate_path, receipt_path, state)
    if not candidate_path.exists():
        candidate_path.write_bytes(encoded)

    target_path = analysis_product_path(type("StoreRoot", (), {"root": state})(), "20260930", "2026-09-29")
    catalog_path = state / "workspace_announcements" / "20260930" / "eastmoney_date_catalog" / "20260929" / "latest.json"
    state_catalog = load_json(catalog_path)
    if (state_catalog.get("run_id") != catalog.get("run_id")
            or state_catalog.get("sha256") != catalog.get("sha256")
            or state_catalog.get("sha256") != digest({key: value for key, value in state_catalog.items() if key != "sha256"})):
        raise ValueError("LIVE_OWNER_STATE_CATALOG_DIFFERS_FROM_CANARY")

    prior_exists = target_path.exists()
    prior_sha = file_sha(target_path) if prior_exists else None
    product_sha = product["sha256"]
    prior_product_sha = None
    if prior_exists:
        prior_product = load_json(target_path)
        # Validate the existing product's canonical self-digest and source/date
        # binding, then compare product digests. Raw file SHA includes JSON
        # formatting and must not be compared with the embedded product SHA.
        validate_product(prior_product, target_trade_date="20260930",
                         publication_date="2026-09-29", catalog=state_catalog)
        prior_product_sha = prior_product.get("sha256")
        if prior_product_sha != product_sha:
            raise ValueError("EXISTING_DERIVED_PRODUCT_DIFFERS; NO_OVERWRITE")
    receipt = {
        "schema_version": "v4.manager_research.announcement_analysis_import_dry_run.v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": "DRY_RUN_ONLY",
        "state_root": str(state),
        "owner_catalog_path": str(catalog_path),
        "owner_catalog_run_id": catalog["run_id"],
        "owner_catalog_sha256": catalog["sha256"],
        "derived_product_path": str(target_path),
        "derived_product_preexisted": prior_exists,
        "derived_product_prior_sha256": prior_sha,
        "derived_product_prior_product_sha256": prior_product_sha,
        "candidate_path": str(candidate_path),
        "candidate_file_sha256": hashlib.sha256(encoded).hexdigest(),
        "candidate_product_sha256": product_sha,
        "counts": EXPECTED_COUNTS,
        "rollback": ("No owner state was changed. If a later approved integration creates this file, remove only this file after confirming its raw-byte SHA-256 equals candidate_file_sha256. If a previous file is ever authorized for replacement, preserve and restore that exact prior file by its raw-byte derived_product_prior_sha256; derived_product_prior_product_sha256 is the embedded canonical product digest."),
        "written_to_owner_state": False,
    }
    receipt_bytes = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    if receipt_path.exists() and receipt_path.read_bytes() != receipt_bytes:
        raise FileExistsError("DRY_RUN_RECEIPT_EXISTS_WITH_DIFFERENT_CONTENT")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path, receipt_path = _resolve_safe_outputs(candidate_path, receipt_path, state)
    if not receipt_path.exists():
        receipt_path.write_bytes(receipt_bytes)
    print(json.dumps({"status": "DRY_RUN_READY", "receipt": str(receipt_path),
                      "candidate": str(candidate_path), "product_sha256": product_sha,
                      "owner_state_written": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
