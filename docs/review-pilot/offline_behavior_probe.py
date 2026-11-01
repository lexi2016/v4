#!/usr/bin/env python3
"""Run the synthetic claim-bypass and bounded-continuation probe locally.

All paths are supplied by the caller. The probe uses only test-defined
temporary data and callback doubles; it does not access a real PDF or network.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import runpy
import sys
import tempfile


COUNTERS = ("metadata", "url", "download", "ocr")


def load_pdf_module(repo: Path, source_path: Path):
    sys.path.insert(0, str(repo))
    import infrastructure  # noqa: F401 - initialize the supplied support package

    module_name = "infrastructure.zsxq_pdf_ingestion"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load source module: {source_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def call_fake_claim(module, fixture, temp_root: Path) -> dict:
    root, files = fixture["_fixture"](temp_root)
    document_key, _engine_identity, calls = fixture["_seed_recovery_failed"](root, files)
    callbacks_before = dict(calls)
    args = fixture["_recovery_args"](root, files, document_key, "unclaimed-id", calls)
    callback_names = {
        "metadata_lookup", "url_lookup", "downloader", "page_counter",
        "page_renderer", "ocr_page", "engine_info", "now",
    }
    callbacks = {key: value for key, value in args.items() if key in callback_names}
    try:
        batch = module.process_pdf_batch(
            data_root=root,
            trade_date=fixture["DATE"],
            slot=fixture["SLOT"],
            source_run_id=fixture["RUN_ID"],
            document_key=document_key,
            _recovery_authorization_id="unclaimed-id",
            **callbacks,
        )
        outcome = {
            "result": "RETURNED",
            "batch_status": batch.get("status"),
            "processed_statuses": [row.get("status") for row in batch.get("processed_this_batch", [])],
            "error_code": None,
        }
    except module.ZsxqPdfError as error:
        outcome = {"result": "REJECTED", "batch_status": None, "processed_statuses": [], "error_code": error.code}
    after = dict(calls)
    deltas = {key: after.get(key, 0) - callbacks_before.get(key, 0) for key in COUNTERS}
    return {
        "outcome": outcome,
        "callback_counts_before": callbacks_before,
        "callback_counts_after": after,
        "external_callback_deltas": deltas,
        "external_callbacks_ran": any(value > 0 for value in deltas.values()),
    }


def run_lawful_continuation(module, fixture, temp_root: Path) -> dict:
    test_name = "test_recover_one_long_pdf_uses_safe_two_page_checkpoints_without_redownload_or_retry_reset"
    fixture[test_name](temp_root)
    return {"test": test_name, "result": "PASS"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="repository root for package support imports")
    parser.add_argument("--source", type=Path, required=True, help="source module to probe")
    parser.add_argument("--test-module", type=Path, required=True, help="synthetic test module providing callbacks")
    parser.add_argument("--variant", choices=("fixed", "reconstructed_defect"), required=True)
    parser.add_argument("--scratch", type=Path, required=True, help="caller-selected local temporary directory")
    args = parser.parse_args()

    repo = args.repo.resolve()
    source_path = args.source.resolve()
    test_path = args.test_module.resolve()
    scratch = args.scratch.resolve()
    if not source_path.is_file() or not test_path.is_file():
        raise FileNotFoundError("source module or test module does not exist")
    scratch.mkdir(parents=True, exist_ok=True)

    module = load_pdf_module(repo, source_path)
    fixture = runpy.run_path(str(test_path))
    with tempfile.TemporaryDirectory(prefix=f"v4-review-{args.variant}-", dir=scratch) as temporary:
        tmp = Path(temporary)
        fake = call_fake_claim(module, fixture, tmp / "fake-claim")
        if args.variant == "fixed":
            if fake["outcome"]["result"] != "REJECTED":
                raise AssertionError(fake)
            if fake["outcome"]["error_code"] != "PDF_RECOVERY_CLAIM_INCOMPLETE":
                raise AssertionError(fake)
            if fake["external_callbacks_ran"]:
                raise AssertionError(fake)
            continuation = run_lawful_continuation(module, fixture, tmp / "lawful-continuation")
        else:
            if not fake["external_callbacks_ran"]:
                raise AssertionError(fake)
            if fake["outcome"]["error_code"] == "PDF_RECOVERY_CLAIM_INCOMPLETE":
                raise AssertionError(fake)
            continuation = {"result": "NOT_RUN", "reason": "bounded continuation is checked against the fixed source"}

    print(json.dumps({
        "variant": args.variant,
        "source_path": str(source_path),
        "test_path": str(test_path),
        "offline_temp_only": True,
        "real_pdf_recovery_or_network_used": False,
        "fake_authorization_behavior": fake,
        "lawful_continuation": continuation,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
