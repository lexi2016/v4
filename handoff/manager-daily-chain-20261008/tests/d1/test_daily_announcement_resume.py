from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops import manager_announcement_body_batch as body_batch


APP_ROOT = Path("/Users/lexi/Desktop/学习/v4_app")
CLI_PATH = APP_ROOT / "ops/run_manager_daily_announcement.py"
CATALOG_READ_PATH = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research/"
    "announcement_agent_runs/3f9d37a643060b57992167f3df05d987/evidence/catalog_read.json"
)
FORMAL_MATERIAL_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research/materials"
)
EVIDENCE_RUN_ID = "3f9d37a643060b57992167f3df05d987"


def _cli():
    spec = importlib.util.spec_from_file_location("daily_announcement_cli_resume_test", CLI_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _catalog():
    assert CATALOG_READ_PATH.is_file()
    assert FORMAL_MATERIAL_ROOT.is_dir()
    return json.loads(CATALOG_READ_PATH.read_text(encoding="utf-8"))


def _isolated_state(tmp_path: Path, catalog_read: dict):
    state_root = tmp_path / "manager_auto_research"
    evidence = state_root / "announcement_agent_runs" / EVIDENCE_RUN_ID / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "catalog_read.json").write_bytes(CATALOG_READ_PATH.read_bytes())
    source = body_batch.imports()["MaterialStore"](FORMAL_MATERIAL_ROOT)
    destination = body_batch.imports()["MaterialStore"](state_root / "materials")
    catalog = catalog_read["catalog"]
    for page in catalog["page_receipts"]:
        ref = page["source_ref"]
        blob_rel = source._blob_relative(ref["blob_sha256"])
        source_key = ref["source_key"]
        destination._io.write_bytes(blob_rel, source._io.read_bytes(blob_rel))
        destination._io.write_bytes(
            destination._index_relative(source_key),
            source._io.read_bytes(source._index_relative(source_key)),
        )
    return state_root, evidence


def _namespace(state_root: Path, *, run_id: str = EVIDENCE_RUN_ID,
               target: str = "20261008", publication: str = "2026-10-07"):
    return SimpleNamespace(target_date=target, publication_date=publication,
        resume_evidence_run_id=run_id, research_state_root=str(state_root),
        api_base="http://127.0.0.1:8873")


def _write_complete_body_batch(evidence: Path, catalog_read: dict):
    catalog = catalog_read["catalog"]
    rows = catalog["manager_consumer_rows"]
    article_ids = [row["art_code"] for row in rows]
    input_identity = hashlib.sha256(body_batch.json_bytes({
        "target_trade_date": "20261008", "publication_date": "2026-10-07",
        "catalog_run_id": catalog["run_id"], "catalog_sha256": catalog["sha256"],
        "article_ids": article_ids,
        "listing_body_sha256s": [row["raw_body_sha256"] for row in rows],
    })).hexdigest()
    body_root = evidence / "body_batch"
    body_root.mkdir()
    manifest = {"target_trade_date": "20261008", "publication_date": "2026-10-07",
        "catalog_run_id": catalog["run_id"], "catalog_sha256": catalog["sha256"],
        "input_identity_sha256": input_identity,
        "article_receipts": [{"art_code": art_code, "status": "COMPLETE_CONTENT_API_BODY"}
                              for art_code in article_ids]}
    manifest_raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    (body_root / "body_corpus_manifest.json").write_bytes(manifest_raw)
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    body = {"schema": "v4.manager_research.eastmoney_hk_announcement_body_corpus.v3",
        "target_notice_date": "2026-10-07", "article_count": len(article_ids),
        "input_identity_sha256": input_identity, "source_manifest_sha256": manifest_sha,
        "rows": [{"art_code": art_code} for art_code in article_ids]}
    body_raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    (body_root / "body_corpus.json").write_bytes(body_raw)
    body_sha = hashlib.sha256(body_raw).hexdigest()
    batch = {"schema": "v4.manager_research.announcement_body_batch_receipt.v1",
        "status": "PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS", "target_trade_date": "20261008",
        "publication_date": "2026-10-07", "catalog_run_id": catalog["run_id"],
        "catalog_sha256": catalog["sha256"], "input_identity_sha256": input_identity,
        "article_rows": len(article_ids), "terminal_article_receipts": len(article_ids),
        "body_corpus": "body_corpus.json", "body_corpus_sha256": body_sha,
        "body_corpus_manifest": "body_corpus_manifest.json",
        "body_corpus_manifest_sha256": manifest_sha}
    batch_raw = json.dumps(batch, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    (body_root / "batch_receipt.json").write_bytes(batch_raw)
    return batch


def _owner_get(catalog_read, calls, *, drift=False):
    def request(api_base, path, *, method="GET", payload=None):
        calls.append((method, path, payload))
        result = copy.deepcopy(catalog_read)
        if drift:
            result["catalog"]["sha256"] = "f" * 64
        return result
    return request


def test_resume_is_get_only_and_completed_capture_is_idempotent(tmp_path, monkeypatch):
    cli = _cli()
    catalog_read = _catalog()
    state_root, evidence = _isolated_state(tmp_path, catalog_read)
    calls = []
    batch_runs = []
    monkeypatch.setattr(cli, "_request", _owner_get(catalog_read, calls))

    def run_batch(*args, **kwargs):
        batch_runs.append((args, kwargs))
        return _write_complete_body_batch(evidence, catalog_read)

    monkeypatch.setattr(body_batch, "run_capture", run_batch)
    args = _namespace(state_root)
    first = cli._capture(args)
    second = cli._capture(args)

    assert first == second
    assert first["status"] == "PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS"
    assert first["evidence_run_id"] == EVIDENCE_RUN_ID
    assert len(batch_runs) == 1
    assert [method for method, _path, _payload in calls] == ["GET", "GET"]
    assert (evidence / "capture_receipt.json").is_file()


def test_resume_rejects_wrong_run_id_and_date_before_owner_call(tmp_path, monkeypatch):
    cli = _cli()
    catalog_read = _catalog()
    state_root, evidence = _isolated_state(tmp_path, catalog_read)
    wrong_evidence = state_root / "announcement_agent_runs" / ("0" * 32) / "evidence"
    wrong_evidence.mkdir(parents=True)
    (wrong_evidence / "catalog_read.json").write_bytes((evidence / "catalog_read.json").read_bytes())
    calls = []
    monkeypatch.setattr(cli, "_request", _owner_get(catalog_read, calls))

    with pytest.raises(ValueError, match="ANNOUNCEMENT_RESUME_EVIDENCE_RUN_ID_MISMATCH"):
        cli._capture(_namespace(state_root, run_id="0" * 32))
    with pytest.raises(ValueError, match="ANNOUNCEMENT_RESUME_CATALOG_PAIR_OR_SOURCE_INVALID"):
        cli._capture(_namespace(state_root, target="20261007"))
    assert calls == []


def test_resume_rejects_owner_source_drift_without_body_write(tmp_path, monkeypatch):
    cli = _cli()
    catalog_read = _catalog()
    state_root, evidence = _isolated_state(tmp_path, catalog_read)
    calls = []
    monkeypatch.setattr(cli, "_request", _owner_get(catalog_read, calls, drift=True))

    with pytest.raises(ValueError, match="ANNOUNCEMENT_RESUME_OWNER_CATALOG_DRIFT"):
        cli._capture(_namespace(state_root))
    assert len(calls) == 1 and calls[0][0] == "GET"
    assert not (evidence / "body_batch").exists()
    assert not (evidence / "capture_receipt.json").exists()


def test_resume_rejects_conflicting_existing_capture_receipt(tmp_path, monkeypatch):
    cli = _cli()
    catalog_read = _catalog()
    state_root, evidence = _isolated_state(tmp_path, catalog_read)
    calls = []
    monkeypatch.setattr(cli, "_request", _owner_get(catalog_read, calls))
    monkeypatch.setattr(body_batch, "run_capture",
        lambda *args, **kwargs: _write_complete_body_batch(evidence, catalog_read))
    cli._capture(_namespace(state_root))
    receipt_path = evidence / "capture_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["catalog_product_sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ValueError, match="ANNOUNCEMENT_RESUME_CAPTURE_RECEIPT_CONFLICT"):
        cli._capture(_namespace(state_root))
    assert all(method == "GET" for method, _path, _payload in calls)
