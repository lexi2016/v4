from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


APP_ROOT = Path("/Users/lexi/Desktop/学习/v4_app")
MODULE_PATH = APP_ROOT / "ops/manager_announcement_body_batch.py"
CATALOG_READ_PATH = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research/"
    "announcement_agent_runs/3f9d37a643060b57992167f3df05d987/evidence/catalog_read.json"
)
MATERIAL_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research/materials"
)


def _module():
    spec = importlib.util.spec_from_file_location("manager_announcement_body_batch_test", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _saved_catalog():
    assert CATALOG_READ_PATH.is_file(), "saved exact-date catalog readback is required for offline test"
    assert MATERIAL_ROOT.is_dir(), "saved listing material cache is required for offline test"
    return json.loads(CATALOG_READ_PATH.read_text(encoding="utf-8"))


def _validate(module, catalog_read):
    api = module.imports()
    api["_body_security_match"] = module._body_security_match
    store = api["MaterialStore"](MATERIAL_ROOT)
    rows = module._validate_catalog(api, catalog_read, store, "20261008", "2026-10-07")
    return api, store, rows


def test_actual_613_row_catalog_preserves_all_626_numeric_and_applicant_links():
    module = _module()
    catalog_read = _saved_catalog()
    _, _, rows = _validate(module, catalog_read)

    identities = [identity for row in rows for identity in row["source_issuer_codes"]]
    assert len(rows) == 613
    assert len(identities) == 626
    assert sum(identity["source_stock_code"] == "H2479" for identity in identities) == 3
    assert sum(identity["source_stock_code"].isdigit() for identity in identities) == 623
    assert sum(row["art_code"] == module.APPROVED_CANARY_ARTICLE for row in rows) == 1


@pytest.mark.parametrize(
    ("raw_code", "declared_code"),
    [("H24799", "H24799"), ("H2479", "00700"), ("0700X", "00700")],
)
def test_invalid_or_mismatched_hk_identity_is_rejected(raw_code, declared_code):
    module = _module()
    catalog_read = copy.deepcopy(_saved_catalog())
    catalog = catalog_read["catalog"]
    identity = catalog["manager_consumer_rows"][0]["source_issuer_codes"][0]
    identity["source_stock_code"] = raw_code
    identity["code"] = declared_code

    with pytest.raises(ValueError, match="SAVED_CATALOG_SOURCE_IDENTITY_INVALID"):
        _validate(module, catalog_read)


def test_single_article_canary_is_partial_and_never_writes_full_batch_inputs(tmp_path, monkeypatch):
    module = _module()
    catalog_read = _saved_catalog()
    original_imports = module.imports

    def offline_imports():
        api = original_imports()
        api["HkexOfficialProvider"] = lambda **kwargs: object()
        return api

    def cached_body_only(api, store, provider, gate, row, out_root, target, publication):
        art_code = row["art_code"]
        receipt = {"art_code": art_code, "status": "COMPLETE_CONTENT_API_BODY",
                   "body_status": "COMPLETE_CONTENT_API_BODY", "body_path": f"bodies/{art_code}.json",
                   "body_file_sha256": "a" * 64, "semantic_status": "NOT_REVIEWED"}
        module.atomic_json(out_root / "article_receipts" / f"{art_code}.json", receipt)
        module.atomic_json(out_root / "bodies" / f"{art_code}.json", {"art_code": art_code})
        return receipt

    monkeypatch.setattr(module, "imports", offline_imports)
    monkeypatch.setattr(module, "_capture_article", cached_body_only)
    output = tmp_path / "isolated-one-article-canary"
    result = module.run_capture(catalog_read, MATERIAL_ROOT, output, "20261008", "2026-10-07",
                                canary_article=module.APPROVED_CANARY_ARTICLE)

    assert result["status"] == "CANARY_PARTIAL"
    assert result["formal_import_eligible"] is False
    assert result["completeness"] == "ONE_ARTICLE_ONLY"
    assert result["art_code"] == module.APPROVED_CANARY_ARTICLE
    assert result["article_status"] == "COMPLETE_CONTENT_API_BODY"
    assert (output / "canary_receipt.json").is_file()
    assert not (output / "batch_receipt.json").exists()
    assert not (output / "batch_attempt.json").exists()
    assert not (output / "body_corpus.json").exists()
    assert not (output / "body_corpus_manifest.json").exists()


def test_unknown_canary_rejects_before_creating_output(tmp_path):
    module = _module()
    output = tmp_path / "must-not-be-created"
    with pytest.raises(ValueError, match="BODY_BATCH_CANARY_ARTICLE_OR_DATE_NOT_AUTHORIZED"):
        module.run_capture(_saved_catalog(), MATERIAL_ROOT, output, "20261008", "2026-10-07",
                           canary_article="AN202610071830178358")
    assert not output.exists()


def test_approved_canary_missing_from_catalog_rejects_without_output(tmp_path):
    module = _module()
    catalog_read = copy.deepcopy(_saved_catalog())
    catalog = catalog_read["catalog"]
    catalog["manager_consumer_rows"] = [
        row for row in catalog["manager_consumer_rows"]
        if row["art_code"] != module.APPROVED_CANARY_ARTICLE
    ]
    catalog["manager_consumer_row_count"] -= 1
    output = tmp_path / "missing-canary"
    with pytest.raises(ValueError, match="BODY_BATCH_CANARY_ARTICLE_NOT_IN_VERIFIED_CATALOG"):
        module.run_capture(catalog_read, MATERIAL_ROOT, output, "20261008", "2026-10-07",
                           canary_article=module.APPROVED_CANARY_ARTICLE)
    assert not output.exists()


def test_cli_normalizes_string_paths_before_catalog_validation(tmp_path):
    catalog_path = tmp_path / "invalid-catalog.json"
    catalog_path.write_text(json.dumps({"readback_status": "UNVERIFIED"}), encoding="utf-8")
    output = tmp_path / "must-not-be-created"
    result = subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),
            "--catalog-read", str(catalog_path),
            "--material-root", str(tmp_path / "empty-material-cache"),
            "--output-root", str(output),
            "--target-date", "20261008",
            "--publication-date", "2026-10-07",
        ],
        cwd=APP_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert "SAVED_CATALOG_BINDING_OR_SAFETY_MISMATCH" in result.stderr
    assert "AttributeError" not in result.stderr
    assert not output.exists()
