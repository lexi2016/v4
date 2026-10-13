"""Future-new-article frozen-input and strict Stage A canaries.

The fixtures are synthetic and exercise the existing package/import and V4
index paths. They do not call Chat, Drive, OCR, a live API, or a production
service.
"""
from __future__ import annotations

import csv
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

HERE = Path(__file__).resolve()
V3_ROOT = HERE.parents[1]
V4_ROOT = Path(os.environ.get("WECHAT_REVIEW_V4_ROOT", str(HERE.parents[4] / "v4_app"))).expanduser()
sys.path.insert(0, str(V3_ROOT / "scripts"))
sys.path.insert(0, str(V4_ROOT))

import wechat_chat_handoff as handoff
from test_wechat_chat_handoff import _make_run
from infrastructure.wechat_research_archive import ArchiveError, WechatResearchArchive
from ops.index_wechat_research import register_return
from apps.api.v35_api.wechat_research_router import create_wechat_research_router


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def package(tmp_path: Path, *, count: int, package_id: str = "standard_fixture_v1"):
    run = _make_run(tmp_path, count=count)
    out = tmp_path / "package"
    receipt = handoff.package_run(run, out, package_id)
    return run, out / receipt["zip"]["path"], receipt


def make_return(tmp_path: Path, package_receipt: dict, *, image_count: int,
                return_id: str = "standard_return_01", status: str = "PARTIAL") -> dict[str, Path]:
    returned = tmp_path / "returned"
    returned.mkdir(exist_ok=True)
    paths = {key: returned / name for key, name in {
        "report": "report.md", "coverage": "coverage.csv", "mentions": "mentions.csv",
        "unmapped": "unmapped.csv", "summary": "summary.json",
    }.items()}
    sources = ["BODY", *(f"IMAGE{n:03d}" for n in range(1, image_count + 1))]
    coverage_columns = "source_index,event,subject,claim,date,number,unit,source_grade,uncertainty,original_checked,original_scope,text_read".split(",")
    coverage_rows = []
    for source in sources:
        coverage_rows.append({
            "source_index": source,
            "event": "EVENT" if source == "BODY" else "NO_EVENT",
            "subject": "fixture", "claim": "synthetic source reviewed", "date": "",
            "number": "", "unit": "", "source_grade": "UNKNOWN", "uncertainty": "",
            "original_checked": "false", "original_scope": "NOT_APPLICABLE" if source == "BODY" else "NONE",
            "text_read": "true",
        })
    write_csv(paths["coverage"], coverage_columns, coverage_rows)
    mention_columns = "market,code,name,source_index,mapping_status,source_named_or_derived,claim_context,entity_id,source_name,listing_origin".split(",")
    mention_rows = [dict(market="A", code="000001.SZ", name="Fixture Co", source_index="BODY",
                         mapping_status="NAME_RESOLVED", source_named_or_derived="SOURCE_NAMED",
                         claim_context="synthetic test only", entity_id="fixture_issuer",
                         source_name="Fixture Co", listing_origin="NAME_RESOLVED")]
    write_csv(paths["mentions"], mention_columns, mention_rows)
    paths["unmapped"].write_text("name,reason,source_index\n", encoding="utf-8")
    header = {"package_id": package_receipt["package_id"], "input_digest": package_receipt["input_digest"],
              "return_id": return_id}
    paths["report"].write_text("<!-- wechat-return: " + json.dumps(header) + " -->\n# Synthetic report\nPartial research fixture.\n", encoding="utf-8")
    summary = {
        "schema_version": 2,
        "review_contract_version": package_receipt["review_contract_version"],
        "event_dispositions": {"BODY": "HOLD"},
        "url": package_receipt["original_url"], "package_id": package_receipt["package_id"],
        "input_digest": package_receipt["input_digest"],
        "manifest_sha256": package_receipt["manifest_sha256"], "return_id": return_id,
        "reading_mode": "OCR_RISK_REVIEW", "article_date": package_receipt["article_date"],
        "image_count": image_count,
        "coverage_counts": {"total": len(sources), "EVENT": 1, "NO_EVENT": len(sources) - 1, "UNREADABLE": 0},
        "mentions_counts": {"total": 1, "A": 1, "BJ": 0, "HK": 0, "entities": 1,
                             "source_named_entities": 1, "supplemental_listing_rows": 0},
        "status": status, "missing_inputs": [],
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        "artifact_sha256": {paths[key].name: sha(paths[key].read_bytes())
                             for key in ("report", "coverage", "mentions", "unmapped")},
    }
    write_json(paths["summary"], summary)
    return paths


def import_standard(tmp_path: Path, run: Path, zip_path: Path, package_receipt: dict,
                    returned: dict[str, Path], *, omit: str | None = None):
    args = {
        "source_run_value": run, "package_id_value": package_receipt["package_id"],
        "package_zip_value": zip_path, "package_sha_value": package_receipt["zip"]["sha256"],
        "report_value": returned["report"], "coverage_value": returned["coverage"],
        "mentions_value": returned["mentions"], "unmapped_value": returned["unmapped"],
        "summary_value": returned["summary"], "out_dir_value": tmp_path / "archive",
        "archive_frozen_input": True,
    }
    if omit:
        args[f"{omit}_value"] = ""
    return handoff.import_chat_return(**args)


def v4_reader(tmp_path: Path, archive: Path):
    return WechatResearchArchive(archive, tmp_path / "v4-data" / "research" / "wechat_materials")


def strict_register(tmp_path: Path, archive: Path, receipt: dict):
    path = archive / receipt.get("receipt_filename", "IMPORT_RECEIPT.json")
    return register_return(v4_reader(tmp_path, archive), receipt=path.name,
                           receipt_sha256=sha(path.read_bytes()), require_frozen_input=True)


@pytest.mark.parametrize("image_count", [0, 3], ids=["text-only", "image-package"])
def test_new_standard_archives_exact_frozen_members_and_indexes_partial_report(tmp_path, image_count):
    run, zip_path, package_receipt = package(tmp_path, count=image_count,
                                             package_id=f"standard_fixture_{image_count}_v1")
    returned = make_return(tmp_path, package_receipt, image_count=image_count,
                           return_id=f"standard_return_{image_count}", status="PARTIAL")
    imported = import_standard(tmp_path, run, zip_path, package_receipt, returned)
    assert imported["status"] == "REPORT_AND_STRUCTURED_ARCHIVED"
    assert imported["local_acceptance"]["semantic_research_accepted"] is False
    frozen = imported["frozen_input"]
    assert set(("manifest_path", "manifest_sha256", "receipt_path", "receipt_sha256")).issubset(frozen)
    assert frozen["status"] == "VERIFIED"
    archive = tmp_path / "archive"
    base = archive / Path(frozen["manifest_path"]).parent
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        extraction = json.loads((archive / frozen["receipt_path"]).read_text(encoding="utf-8"))
        assert [row["name"] for row in extraction["members"]] == names
        for name in names:
            assert (base / name).read_bytes() == zf.read(name)
    frozen_receipt_bytes = (archive / frozen["receipt_path"]).read_bytes()
    again = import_standard(tmp_path, run, zip_path, package_receipt, returned)
    assert again == imported
    assert (archive / frozen["receipt_path"]).read_bytes() == frozen_receipt_bytes

    registered = strict_register(tmp_path, archive, imported)
    assert registered["status"] == "INDEXED"
    record = v4_reader(tmp_path, archive).detail(registered["record_id"])
    assert record["material"]["states"]["research_review"] == "NOT_EVALUATED_STAGE_A"
    assert record["material"]["available_at"] is None
    assert record["material"]["receipt_claims"]["semantic_research_accepted"] is False
    claims = record["material"]["receipt_claims"]
    assert claims["bytes_archived"] is True
    assert claims["input_binding_valid"] is True
    assert claims["structure_valid"] is True
    assert claims["chat_claimed_complete"] is False
    assert record["report"]["content"].encode("utf-8") == returned["report"].read_bytes()
    assert strict_register(tmp_path, archive, imported)["idempotent"] is True

    app = FastAPI()
    app.include_router(create_wechat_research_router(v4_reader(tmp_path, archive)), prefix="/api/v3/research")
    client = TestClient(app)
    article_date = imported["binding"]["article_date"]
    listed = client.get("/api/v3/research/wechat/materials",
                        params={"date": article_date, "date_basis": "article"})
    assert listed.status_code == 200
    assert [row["record_id"] for row in listed.json()["items"]] == [registered["record_id"]]
    assert listed.json()["items"][0]["article"]["article_date"] == article_date
    report = client.get(f"/api/v3/research/wechat/materials/{registered['record_id']}")
    assert report.status_code == 200
    assert report.json()["report"]["content"].encode("utf-8") == returned["report"].read_bytes()
    report_bytes = client.get(f"/api/v3/research/wechat/materials/{registered['record_id']}/artifacts/report")
    assert report_bytes.status_code == 200
    assert report_bytes.content == returned["report"].read_bytes()
    with zipfile.ZipFile(zip_path) as zf:
        for source in json.loads((archive / frozen["receipt_path"]).read_text(encoding="utf-8"))["descriptor_sources"]:
            assert v4_reader(tmp_path, archive).artifact(
                registered["record_id"], "source_" + source["source_id"]
            )[0] == zf.read(source["path"])


def test_standard_archive_with_missing_return_file_is_not_strictly_indexable(tmp_path):
    run, zip_path, package_receipt = package(tmp_path, count=0, package_id="missing_return_fixture_v1")
    returned = make_return(tmp_path, package_receipt, image_count=0)
    imported = import_standard(tmp_path, run, zip_path, package_receipt, returned, omit="mentions")
    assert imported["status"] == "REPORT_WITH_STRUCTURED_PARTIAL"
    assert "mentions.csv" in imported["missing_artifacts"]
    archive = tmp_path / "archive"
    with pytest.raises(ArchiveError, match="FROZEN_INPUT_RETURN_INCOMPLETE"):
        strict_register(tmp_path, archive, imported)
    assert not (tmp_path / "v4-data" / "research" / "wechat_materials" / "records").exists()


def test_empty_invalid_return_is_preserved_as_exact_raw_bytes(tmp_path):
    run, zip_path, package_receipt = package(tmp_path, count=0, package_id="empty_return_fixture_v1")
    returned = make_return(tmp_path, package_receipt, image_count=0)
    returned["mentions"].write_bytes(b"")
    imported = import_standard(tmp_path, run, zip_path, package_receipt, returned)
    archived = tmp_path / "archive" / imported["archived_files"]["mentions"]["archived_filename"]
    assert archived.read_bytes() == b""
    assert "mentions.csv" in imported["invalid_artifacts"]
    with pytest.raises(ArchiveError, match="INVALID_ARTIFACT_SIZE"):
        strict_register(tmp_path, tmp_path / "archive", imported)


def test_bad_frozen_zip_is_retained_as_raw_return_with_blocker(tmp_path):
    run, zip_path, package_receipt = package(tmp_path, count=0, package_id="bad_zip_fixture_v1")
    returned = make_return(tmp_path, package_receipt, image_count=0)
    original = zip_path.read_bytes()
    zip_path.write_bytes(original + b"tamper")
    imported = import_standard(tmp_path, run, zip_path, package_receipt, returned)
    assert imported["status"] != "REPORT_AND_STRUCTURED_ARCHIVED"
    assert imported["archived_files"]["report"]["sha256"] == sha(returned["report"].read_bytes())
    assert imported["frozen_input"]["status"] == "BLOCKED"
    assert "SHA-256" in imported["frozen_input"]["blockers"][0]


def test_v4_strict_rejects_mutated_source_path_and_timezone_precision_is_preserved(tmp_path):
    run, zip_path, package_receipt = package(tmp_path, count=0, package_id="strict_tamper_fixture_v1")
    returned = make_return(tmp_path, package_receipt, image_count=0)
    imported = import_standard(tmp_path, run, zip_path, package_receipt, returned)
    archive = tmp_path / "archive"
    source = archive / Path(imported["frozen_input"]["manifest_path"]).parent / "BODY.md"
    source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(ArchiveError, match="FROZEN_INPUT_MEMBER_HASH_MISMATCH"):
        strict_register(tmp_path, archive, imported)
    assert not (tmp_path / "v4-data" / "research" / "wechat_materials" / "records").exists()


@pytest.mark.parametrize("value,expected", [
    ("2026-09-17T22:53+08:00", "2026-09-17T22:53+08:00"),
    ("2026-09-17T22:53:30+08:00", "2026-09-17T22:53:30+08:00"),
    ("2026-09-17T22:53", None),
    ("2026-13-17T22:53+08:00", None),
])
def test_aware_time_accepts_zoned_minute_or_second_precision_without_reformatting(value, expected):
    from infrastructure.wechat_research_archive import aware_time
    assert aware_time(value) == expected


def test_article_day_conflict_remains_a_hard_stage_a_blocker():
    from infrastructure.wechat_research_archive import make_snapshot
    receipt = {
        "binding": {"article_url": "https://mp.weixin.qq.com/s/example", "article_date": "20260917",
                    "package_identity_status": "VERIFIED", "input_digest": "a" * 64,
                    "package_id": "fixture", "source_run_id": "fixture", "package_sha256_declared": "b" * 64,
                    "package_sha256_observed": "b" * 64, "package_sha256_status": "VERIFIED"},
        "received_at": "2026-09-18T00:00+08:00", "archived_files": {"report": {}},
        "missing_artifacts": ["coverage.csv", "mentions.csv", "unmapped.csv", "summary.json"],
        "local_acceptance": {}, "structured_validation_status": "MISSING",
    }
    with pytest.raises(ArchiveError, match="IDENTITY_CONFLICT_PUBLISHED_DATE"):
        make_snapshot(receipt, {"report": {}}, receipt_sha="c" * 64,
                      indexed_at="2026-09-18T00:00+00:00",
                      manifest_identity={"published_at": "2026-09-17T22:53+08:00",
                                         "article_date": "20260918"}, return_id=None)


def test_event_disposition_omission_keeps_raw_return_but_blocks_strict_registration(tmp_path):
    run, zip_path, package_receipt = package(tmp_path, count=0, package_id="omitted_disposition_v1")
    returned = make_return(tmp_path, package_receipt, image_count=0)
    summary = json.loads(returned["summary"].read_text(encoding="utf-8"))
    summary["event_dispositions"] = {}
    write_json(returned["summary"], summary)
    imported = import_standard(tmp_path, run, zip_path, package_receipt, returned)
    assert imported["status"] == "REPORT_AND_STRUCTURED_INVALID"
    assert imported["frozen_input"]["status"] == "VERIFIED"
    with pytest.raises(ArchiveError, match="FROZEN_INPUT_RETURN_INCOMPLETE"):
        strict_register(tmp_path, tmp_path / "archive", imported)
    assert not (tmp_path / "v4-data" / "research" / "wechat_materials" / "records").exists()


@pytest.mark.parametrize("case,error", [
    ("unsafe_path", "UNSAFE_PATH"),
    ("missing_source", "FROZEN_INPUT_MEMBER_MISSING"),
    ("symlink_source", "UNSAFE_PATH"),
    ("wrong_package", "IDENTITY_CONFLICT_RETURN"),
    ("wrong_manifest_hash", "FROZEN_INPUT_RECEIPT_OR_MANIFEST_HASH_MISMATCH"),
])
def test_strict_frozen_receipt_rejects_tampered_or_missing_sources(tmp_path, case, error):
    run, zip_path, package_receipt = package(tmp_path, count=0, package_id=f"tamper_{case}_v1")
    returned = make_return(tmp_path, package_receipt, image_count=0)
    imported = import_standard(tmp_path, run, zip_path, package_receipt, returned)
    archive = tmp_path / "archive"
    receipt_path = archive / "IMPORT_RECEIPT.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    frozen_base = archive / Path(receipt["frozen_input"]["manifest_path"]).parent
    if case == "unsafe_path":
        receipt["frozen_input"]["manifest_path"] = "../escape/manifest.json"
        write_json(receipt_path, receipt)
    elif case == "missing_source":
        (frozen_base / "BODY.md").unlink()
    elif case == "symlink_source":
        original = (frozen_base / "BODY.md").read_bytes()
        target = tmp_path / "outside.md"
        target.write_bytes(original)
        (frozen_base / "BODY.md").unlink()
        (frozen_base / "BODY.md").symlink_to(target)
    elif case == "wrong_package":
        receipt["binding"]["package_id"] = "different-package"
        write_json(receipt_path, receipt)
    elif case == "wrong_manifest_hash":
        receipt["frozen_input"]["manifest_sha256"] = "0" * 64
        write_json(receipt_path, receipt)
    with pytest.raises(ArchiveError, match=error):
        register_return(v4_reader(tmp_path, archive), receipt=receipt_path.name,
                        receipt_sha256=sha(receipt_path.read_bytes()), require_frozen_input=True)
    assert not (tmp_path / "v4-data" / "research" / "wechat_materials" / "records").exists()

