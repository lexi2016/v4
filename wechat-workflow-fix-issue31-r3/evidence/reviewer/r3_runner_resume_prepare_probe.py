"""Reviewer-only end-to-end probe for anchored saved-HTML legacy adoption.

It reuses the fixture builder only to create a cryptographically consistent
offline package; the adoption and resume stages run through the frozen
candidate runner, fetch adapter child process, and prepare_ocr child process.
No collector or network call is made during the reviewed stages.
"""
from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch

import wechat_article_fetch as fetch
import wechat_pipeline_runner as runner
from test_wechat_article_fetch_recovery import (
    URL,
    WechatArticleFetchRecoveryTests,
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


fixture = WechatArticleFetchRecoveryTests(
    "test_runner_adopts_frozen_legacy_source_then_prepare_reuses_cache"
)
fixture.setUp()
try:
    run_dir, frozen_zip, source_summary, source_manifest, frozen = (
        fixture._prepare_historical_package_fixture()
    )
    summary = json.loads((run_dir / "wechat_article_intake_summary.json").read_text(encoding="utf-8-sig"))
    if int(summary["http_status"]) != 0:
        raise AssertionError("fixture did not model saved-HTML http_status=0")
    preserved_names = (
        "wechat_article_intake_summary.json",
        "wechat_article_raw.html",
        "windows_ocr_results.json",
        "windows_ocr_checkpoint.json",
        "wechat_article_ocr_text.txt",
        "wechat_article_ocr_summary.json",
    )
    before = {name: sha(run_dir / name) for name in preserved_names}
    manifest_path = run_dir / "wechat_article_image_manifest.csv"
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        before_fields, before_rows = list(reader.fieldnames or []), list(reader)
    source_projection_before = fetch._image_source_projection_sha256(before_fields, before_rows)
    image_paths_before = [row["local_path"] for row in before_rows]
    slice_manifest_path = run_dir / "ocr_slice_manifest.json"
    old_slice_manifest_sha = sha(slice_manifest_path)
    collector_calls = fixture.collector_calls.read_text()
    stdout = io.StringIO()
    adoption_args = [
        "--run-dir", str(run_dir), "--url", URL,
        "--title", summary["title"], "--target-date", summary["article_date"],
        "--stage", "fetch",
        "--adopt-frozen-package", str(frozen_zip),
        "--adopt-package-sha256", frozen["package_sha256"],
        "--adopt-package-id", frozen["package_id"],
        "--adopt-input-digest", frozen["input_digest"],
        "--legacy-source-summary", str(source_summary),
        "--legacy-source-manifest", str(source_manifest),
    ]
    with contextlib.redirect_stdout(stdout), patch.object(runner.sys, "platform", "darwin"):
        fetch_rc = runner.main(adoption_args)
    if fetch_rc != 0:
        raise AssertionError(f"runner fetch adoption returned {fetch_rc}: {stdout.getvalue()}")

    # Remove only the derived prepare checkpoint so the runner must execute
    # its actual prepare_ocr child while preserving the OCR result cache.
    slice_manifest_path.unlink()
    with contextlib.redirect_stdout(stdout):
        resume_rc = runner.main([
            "--run-dir", str(run_dir), "--url", URL,
            "--title", summary["title"], "--target-date", summary["article_date"],
            "--stage", "fetch,prepare_ocr", "--resume",
        ])
    if resume_rc != 0:
        raise AssertionError(f"runner fetch-resume/prepare returned {resume_rc}: {stdout.getvalue()}")
    after = {name: sha(run_dir / name) for name in preserved_names}
    if before != after:
        raise AssertionError(f"source/OCR bytes changed during prepare_ocr: before={before}, after={after}")
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        after_fields, after_rows = list(reader.fieldnames or []), list(reader)
    if fetch._image_source_projection_sha256(after_fields, after_rows) != source_projection_before:
        raise AssertionError("prepare_ocr changed the stable ordered source-manifest projection")
    if [row["local_path"] for row in after_rows] != image_paths_before:
        raise AssertionError("prepare_ocr changed the already-rebound in-run image paths")
    new_slice_manifest = json.loads(slice_manifest_path.read_text(encoding="utf-8-sig"))
    if new_slice_manifest.get("status") != "PREPARED" or new_slice_manifest.get("image_count") != 50:
        raise AssertionError("runner did not recreate a valid prepare_ocr checkpoint")
    for item in new_slice_manifest.get("images", []):
        image_path = Path(item.get("image_path") or "").resolve()
        if image_path.parent != (run_dir / "wechat_article_images").resolve() or not image_path.is_file():
            raise AssertionError("prepare_ocr did not resolve every image under the isolated run root")
        if sha(image_path) != item.get("image_sha256"):
            raise AssertionError("prepare_ocr recorded an image hash different from the source bytes")
    if len(new_slice_manifest.get("images", [])) != 50:
        raise AssertionError("prepare_ocr did not resolve every image under the isolated run root")
    if fixture.collector_calls.read_text() != collector_calls:
        raise AssertionError("collector was invoked after anchored adoption")
    state = json.loads((run_dir / "wechat_article_fetch_state.json").read_text(encoding="utf-8-sig"))
    receipts = list((run_dir / "evidence" / "wechat_article_fetch_adoptions").glob("*/REVALIDATION_RECEIPT.json"))
    if len(receipts) != 1 or state.get("collector_invoked") is not False or state.get("network_attempts") != 0:
        raise AssertionError("adoption receipt or zero-network state is missing/invalid")
    print(json.dumps({
        "status": "PASS",
        "source_http_status": summary["http_status"],
        "fetch_runner_exit": fetch_rc,
        "resume_runner_exit": resume_rc,
        "runner_output": stdout.getvalue().splitlines(),
        "revalidation_receipt_count": len(receipts),
        "collector_calls_during_adoption_and_resume": 0,
        "source_and_ocr_result_sha256_stable": True,
        "prepare_checkpoint_recreated": True,
        "old_prepare_checkpoint_sha256": old_slice_manifest_sha,
        "new_prepare_checkpoint_sha256": sha(slice_manifest_path),
        "adoption_state": state["status"],
        "next_missing_stage": state["next_missing_stage"],
    }, ensure_ascii=False, sort_keys=True))
finally:
    fixture.tearDown()
