from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from wechat_chat_handoff import HandoffError, _validate_package_zip, import_chat_return, package_run  # noqa: E402


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_run(tmp_path: Path, count: int = 3) -> Path:
    run = tmp_path / "20260919_chat_fixture"
    image_root = run / "wechat_article_images"
    image_root.mkdir(parents=True)
    urls = [f"https://mmbiz.qpic.cn/fixture/{index}" for index in range(1, count + 1)]
    rows: list[dict[str, str]] = []
    results = []
    html_images = []
    for index, url in enumerate(urls, start=1):
        image = image_root / f"img_{index:02d}.jpg"
        Image.new("RGB", (10, 20), (index, 0, 0)).save(image, format="JPEG")
        data = image.read_bytes()
        digest = _sha(data)
        rows.append({
            "idx": str(index),
            "url": url,
            "local_path": f"runs/{run.name}/wechat_article_images/{image.name}",
            "download_status": f"OK bytes={len(data)}",
            "image_size": "10x20",
            "image_sha256": digest,
            "sha256": digest,
            "bytes": str(len(data)),
        })
        results.append({
            "index": index,
            "name": image.name,
            "path": str(image),
            "image_sha256": digest,
            "status": "OCR_OK",
            "text": f"fixture OCR {index}",
            "text_length": len(f"fixture OCR {index}"),
            "parts": [],
            "error": "",
        })
        html_images.append(f'<img data-src="{url}" />')
    manifest = run / "wechat_article_image_manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = list(rows[0]) if rows else [
            "idx", "url", "local_path", "download_status", "image_size",
            "image_sha256", "sha256", "bytes",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    (run / "wechat_article_raw.html").write_text(
        '<div id="js_content"><p>fixture body</p>' + "".join(html_images) + "</div>",
        encoding="utf-8",
    )
    _write_json(run / "wechat_article_intake_summary.json", {
        "identity_status": "PASS",
        "canonical_url": "https://mp.weixin.qq.com/s/fixture-token",
        "title": "fixture article",
        "account_name": "fixture account",
        "biz": "fixture-biz",
        "raw_publish_time": "1789656810",
        "article_date": "20260917",
        "content_hash": "fixture-evidence-hash",
        "image_count": count,
    })
    _write_json(run / "wechat_article_ocr_summary.json", {
        "status": "OCR_OK" if count else "OCR_NOT_APPLICABLE",
        "image_count": count,
        "processed_count": count,
        "ok_count": count,
        "timeout_count": 0,
        "error_count": 0,
        "empty_count": 0,
        "text_length": sum(int(row["text_length"]) for row in results),
        **({} if count else {"ocr_applicable": False, "body_source_required": True}),
    })
    _write_json(run / "windows_ocr_results.json", results)
    (run / "wechat_article_ocr_text.txt").write_text(
        "\n\n".join(
            f"=====IMAGE{row['index']:03d} {row['name']} [OCR_OK=====\n{row['text']}"
            for row in results
        ),
        encoding="utf-8",
    )
    return run


def _make_package(run: Path, tmp_path: Path, package_id: str = "fixture_package_v1") -> tuple[Path, dict[str, object]]:
    out = tmp_path / f"package_{package_id}"
    receipt = package_run(run, out, package_id)
    return out / f"wechat_chat_materials_{package_id}.zip", receipt


def _rewrite_zip(destination_path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(destination_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def _write_valid_structured_returns(
    tmp_path: Path, package_receipt: dict[str, object], status: str,
) -> dict[str, Path]:
    coverage = tmp_path / "coverage.csv"
    mentions = tmp_path / "mentions.csv"
    unmapped = tmp_path / "unmapped.csv"
    summary = tmp_path / "summary.json"
    # A real v2 positive fixture; DictWriter prevents accidental missing cells.
    fields = "source_index,event,subject,claim,date,number,unit,source_grade,uncertainty,original_checked,original_scope,text_read".split(",")
    rows = []
    for source in ["BODY", "IMAGE001", "IMAGE002", "IMAGE003"]:
        row = {field: "" for field in fields}
        row.update(source_index=source, event="NO_EVENT", subject="fixture", claim="read",
                   source_grade="UNKNOWN", original_checked="false", text_read="true",
                   original_scope="NOT_APPLICABLE" if source == "BODY" else "NONE")
        rows.append(row)
    with coverage.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    fields = "market,code,name,source_index,mapping_status,source_named_or_derived,claim_context,entity_id,source_name,listing_origin".split(",")
    with mentions.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(dict(market="A", code="000001.SZ", name="Fixture Co", source_index="IMAGE001",
            mapping_status="CONFIRMED", source_named_or_derived="SOURCE_NAMED", claim_context="fixture",
            entity_id="fixture_issuer", source_name="Fixture", listing_origin="NAME_RESOLVED"))
    unmapped.write_text("name,reason,source_index\nunknown,ambiguous,IMAGE002\n", encoding="utf-8")
    report = tmp_path / "report.md"
    header = dict(input_digest=package_receipt["input_digest"], return_id="return_fixture", package_id=package_receipt["package_id"])
    report.write_bytes(("<!-- wechat-return: " + json.dumps(header) + " -->\n").encode() + report.read_bytes())
    _write_json(summary, {
        "schema_version": 2,
        "review_contract_version": package_receipt.get("review_contract_version"),
        "event_dispositions": {},
        "url": "https://mp.weixin.qq.com/s/fixture-token",
        "package_id": package_receipt["package_id"],
        "input_digest": package_receipt["input_digest"],
        "return_id": "return_fixture", "reading_mode": "OCR_RISK_REVIEW",
        "manifest_sha256": package_receipt["manifest_sha256"],
        "article_date": "20260917", "image_count": 3,
        "coverage_counts": {"total": 4, "EVENT": 0, "NO_EVENT": 4, "UNREADABLE": 0},
        "mentions_counts": {"total": 1, "A": 1, "BJ": 0, "HK": 0, "entities": 1, "source_named_entities": 1, "supplemental_listing_rows": 0},
        "status": status, "missing_inputs": [],
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        "artifact_sha256": {path.name: _sha(path.read_bytes()) for path in (report, coverage, mentions, unmapped)},
    })
    return {
        "coverage": coverage,
        "mentions": mentions,
        "unmapped": unmapped,
        "summary": summary,
    }


class ChatHandoffTests(unittest.TestCase):
    def test_package_emits_ordered_ocr_material_and_original_images(self) -> None:
        with tempfile.TemporaryDirectory(prefix="chat_handoff_test_") as raw:
            tmp_path = Path(raw)
            run = _make_run(tmp_path)
            out = tmp_path / "package"
            receipt = package_run(run, out, "fixture_ocr_v1")
            self.assertEqual(receipt["status"], "PACKAGE_READY")
            self.assertEqual(receipt["image_count"], 3)
            package_manifest = (out / "manifest.csv").read_text(encoding="utf-8-sig")
            self.assertIn("images/IMAGE001.jpg", package_manifest)
            self.assertNotIn(str(run), package_manifest)
            body = (out / "BODY.md").read_text()
            self.assertEqual([int(value) for value in re.findall(r"\[IMAGE(\d{3})\]", body)], [1, 2, 3])
            ocr = (out / "OCR_FULL.md").read_text()
            self.assertEqual([int(value) for value in re.findall(r"^=====IMAGE(\d{3})", ocr, re.M)], [1, 2, 3])
            with zipfile.ZipFile(out / "wechat_chat_materials_fixture_ocr_v1.zip") as archive:
                self.assertEqual(len([name for name in archive.namelist() if name.startswith("images/IMAGE")]), 3)
                self.assertEqual(archive.read("images/IMAGE001.jpg"), (run / "wechat_article_images/img_01.jpg").read_bytes())
            prompt = (out / "PROMPT.md").read_text(encoding="utf-8")
            self.assertNotRegex(prompt, r"\{\{[^{}]+\}\}")
            self.assertIn("review_contract_version=wechat-event-dispositions-v1", prompt)
            self.assertIn("event_dispositions", prompt)
            self.assertIn("manifest.json.published_at", prompt)
            self.assertIn("拼音首字母", prompt)
            self.assertIn("上下文推定", prompt)
            self.assertIn("不要求额外外查", prompt)
            self.assertIn("mapping_status=CONTEXT_INFERRED_UNIQUE", prompt)
            self.assertIn("source_named_or_derived=RESEARCHER_DERIVED", prompt)
            self.assertIn("external handoff receipt", prompt)
            self.assertIn("summary.json.status", prompt)
            self.assertNotIn("chat_report_status", prompt)
            self.assertNotIn("package_zip_sha256", prompt)
            self.assertNotIn("drive_grounding_id", prompt)
            self.assertNotIn("package_file_id", prompt)
            self.assertNotIn("return_folder_id", prompt)

    def test_package_accepts_explicit_text_only_article(self) -> None:
        with tempfile.TemporaryDirectory(prefix="chat_handoff_test_") as raw:
            tmp_path = Path(raw)
            run = _make_run(tmp_path, count=0)
            out = tmp_path / "text_only_package"
            receipt = package_run(run, out, "fixture_text_only_v1")

            self.assertEqual(receipt["status"], "PACKAGE_READY")
            self.assertEqual(receipt["image_count"], 0)
            body = (out / "BODY.md").read_text(encoding="utf-8")
            self.assertIn("fixture body", body)
            self.assertNotIn("[IMAGE", body)
            ocr = (out / "OCR_FULL.md").read_text(encoding="utf-8")
            self.assertIn("OCR_NOT_APPLICABLE", ocr)
            self.assertNotIn("=====IMAGE", ocr)
            prompt = (out / "PROMPT.md").read_text(encoding="utf-8")
            self.assertNotIn("IMAGE000", prompt)
            self.assertNotIn("{{", prompt)
            with zipfile.ZipFile(out / "wechat_chat_materials_fixture_text_only_v1.zip") as archive:
                self.assertEqual(archive.read("manifest.csv").decode("utf-8-sig").count("\n"), 1)
                self.assertEqual([name for name in archive.namelist() if name.startswith("images/")], [])
                package_manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(package_manifest["total_images"], 0)
                self.assertEqual(package_manifest["ocr_status"], "OCR_NOT_APPLICABLE")
                self.assertEqual(
                    [entry["source_id"] for entry in package_manifest["input_descriptor"]["sources"]],
                    ["BODY", "OCR_FULL", "IMAGE_MANIFEST"],
                )
            package_zip = out / "wechat_chat_materials_fixture_text_only_v1.zip"
            verified = _validate_package_zip(
                package_zip,
                source_run=run,
                package_id="fixture_text_only_v1",
                declared_sha=str(receipt["zip"]["sha256"]),
                observed_sha=_sha(package_zip.read_bytes()),
            )
            self.assertEqual(verified["package_identity_status"], "VERIFIED")
            self.assertEqual(verified["image_count"], 0)
            self.assertEqual(verified["input_digest"], receipt["input_digest"])

    def test_package_rejects_invalid_image_counts_and_unbound_images(self) -> None:
        for invalid_count in (-1, True, "0", None, 0.0):
            with self.subTest(invalid_count=invalid_count), tempfile.TemporaryDirectory(prefix="chat_handoff_test_") as raw:
                tmp_path = Path(raw)
                run = _make_run(tmp_path, count=0)
                intake_path = run / "wechat_article_intake_summary.json"
                intake = json.loads(intake_path.read_text(encoding="utf-8"))
                intake["image_count"] = invalid_count
                _write_json(intake_path, intake)
                with self.assertRaisesRegex(HandoffError, "image_count"):
                    package_run(run, tmp_path / "package", "fixture_bad_image_count_v1")

        for mutation in ("html_image", "stray_file", "ocr_applicable"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(prefix="chat_handoff_test_") as raw:
                tmp_path = Path(raw)
                run = _make_run(tmp_path, count=0)
                if mutation == "html_image":
                    (run / "wechat_article_raw.html").write_text(
                        '<div id="js_content"><p>fixture body</p><img src="https://mmbiz.qpic.cn/unbound"></div>',
                        encoding="utf-8",
                    )
                elif mutation == "stray_file":
                    (run / "wechat_article_images/unlisted.jpg").write_bytes(b"unmanifested")
                else:
                    ocr_path = run / "wechat_article_ocr_summary.json"
                    ocr_summary = json.loads(ocr_path.read_text(encoding="utf-8"))
                    ocr_summary["status"] = "OCR_OK"
                    _write_json(ocr_path, ocr_summary)
                with self.assertRaises(HandoffError):
                    package_run(run, tmp_path / "package", "fixture_unbound_image_v1")

    def test_package_rejects_incomplete_or_wrong_identity_inputs(self) -> None:
        for mutation in ("wrong_order", "empty_image", "missing_image", "bad_identity", "empty_ocr", "missing_ocr_counters"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(prefix="chat_handoff_test_") as raw:
                tmp_path = Path(raw)
                run = _make_run(tmp_path)
                if mutation == "wrong_order":
                    manifest = run / "wechat_article_image_manifest.csv"
                    rows = list(csv.DictReader(manifest.read_text().splitlines()))
                    rows[0]["idx"], rows[1]["idx"] = rows[1]["idx"], rows[0]["idx"]
                    with manifest.open("w", encoding="utf-8", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                        writer.writeheader()
                        writer.writerows(rows)
                elif mutation == "empty_image":
                    (run / "wechat_article_images/img_02.jpg").write_bytes(b"")
                elif mutation == "missing_image":
                    (run / "wechat_article_images/img_02.jpg").unlink()
                elif mutation == "bad_identity":
                    path = run / "wechat_article_intake_summary.json"
                    value = json.loads(path.read_text())
                    value["canonical_url"] = "https://example.com/wrong"
                    _write_json(path, value)
                elif mutation == "empty_ocr":
                    path = run / "windows_ocr_results.json"
                    value = json.loads(path.read_text())
                    value[1]["text"] = ""
                    _write_json(path, value)
                else:
                    path = run / "wechat_article_ocr_summary.json"
                    value = json.loads(path.read_text())
                    for key in ("timeout_count", "error_count", "empty_count"):
                        value.pop(key)
                    _write_json(path, value)
                with self.assertRaises(HandoffError):
                    package_run(run, tmp_path / "package", "fixture_ocr_v1")

    def test_import_preserves_report_bytes_missing_state_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="chat_handoff_test_") as raw:
            tmp_path = Path(raw)
            run = _make_run(tmp_path)
            report = tmp_path / "report.md"
            report_bytes = "# user return\n数字保留原样\n".encode("utf-8")
            report.write_bytes(report_bytes)
            package_zip, package_receipt = _make_package(run, tmp_path)
            package_sha = _sha(package_zip.read_bytes())
            out = tmp_path / "returns"
            kwargs = dict(
                source_run_value=run,
                package_id_value="fixture_package_v1",
                package_zip_value=package_zip,
                package_sha_value=package_sha,
                report_value=report,
                coverage_value="",
                mentions_value="",
                unmapped_value="",
                summary_value="",
                out_dir_value=out,
            )
            first = import_chat_return(**kwargs)
            archived = out / first["archived_files"]["report"]["archived_filename"]
            self.assertEqual(first["status"], "REPORT_ONLY_ARCHIVED")
            self.assertEqual(first["binding"]["package_identity_status"], "VERIFIED")
            self.assertEqual(first["binding"]["package_id_binding_status"], "VERIFIED")
            self.assertEqual(first["missing_artifacts"], ["coverage.csv", "mentions.csv", "unmapped.csv", "summary.json"])
            self.assertEqual(archived.read_bytes(), report_bytes)
            second = import_chat_return(**kwargs)
            self.assertEqual(second["received_at"], first["received_at"])
            self.assertEqual(len(list(out.glob("report*.md"))), 1)
            returns = _write_valid_structured_returns(
                tmp_path, package_receipt, "COMPLETE_WITH_ALL_SOURCES"
            )
            complete = import_chat_return(**{
                **kwargs,
                "coverage_value": returns["coverage"],
                "mentions_value": returns["mentions"],
                "unmapped_value": returns["unmapped"],
                "summary_value": returns["summary"],
            })
            self.assertEqual(complete["status"], "REPORT_AND_STRUCTURED_ARCHIVED")
            self.assertEqual(complete["missing_artifacts"], [])
            self.assertFalse(complete["local_acceptance"]["chat_self_reported_numbers_accepted"])

    def test_import_rejects_verified_status_claims_and_legacy_status_field(self) -> None:
        for status in ("RESEARCH_VERIFIED", "API_VERIFIED", "UI_VERIFIED", "NATURAL_VERIFIED"):
            with self.subTest(status=status), tempfile.TemporaryDirectory(prefix="chat_handoff_test_") as raw:
                tmp_path = Path(raw)
                run = _make_run(tmp_path)
                package_zip, package_receipt = _make_package(run, tmp_path)
                report = tmp_path / "report.md"
                report.write_bytes(b"report")
                returns = _write_valid_structured_returns(tmp_path, package_receipt, status)
                receipt = import_chat_return(
                    source_run_value=run,
                    package_id_value="fixture_package_v1",
                    package_zip_value=package_zip,
                    package_sha_value=_sha(package_zip.read_bytes()),
                    report_value=report,
                    coverage_value=returns["coverage"],
                    mentions_value=returns["mentions"],
                    unmapped_value=returns["unmapped"],
                    summary_value=returns["summary"],
                    out_dir_value=tmp_path / "returns",
                )
                self.assertEqual(receipt["status"], "REPORT_AND_STRUCTURED_INVALID")
                self.assertIn("summary.json", receipt["invalid_artifacts"])

        with tempfile.TemporaryDirectory(prefix="chat_handoff_test_") as raw:
            tmp_path = Path(raw)
            run = _make_run(tmp_path)
            package_zip, package_receipt = _make_package(run, tmp_path)
            report = tmp_path / "report.md"
            report.write_bytes(b"report")
            returns = _write_valid_structured_returns(tmp_path, package_receipt, "CANNOT_CONFIRM")
            value = json.loads(returns["summary"].read_text(encoding="utf-8"))
            value.pop("status")
            value["chat_report_status"] = "COMPLETE_WITH_ALL_SOURCES"
            _write_json(returns["summary"], value)
            receipt = import_chat_return(
                source_run_value=run,
                package_id_value="fixture_package_v1",
                package_zip_value=package_zip,
                package_sha_value=_sha(package_zip.read_bytes()),
                report_value=report,
                coverage_value=returns["coverage"],
                mentions_value=returns["mentions"],
                unmapped_value=returns["unmapped"],
                summary_value=returns["summary"],
                out_dir_value=tmp_path / "returns",
            )
            self.assertEqual(receipt["status"], "REPORT_AND_STRUCTURED_INVALID")
            self.assertIn("summary.json", receipt["invalid_artifacts"])

    def test_import_new_report_gets_immutable_version_and_rejects_bad_package_hash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="chat_handoff_test_") as raw:
            tmp_path = Path(raw)
            run = _make_run(tmp_path)
            report = tmp_path / "report.md"
            report.write_bytes(b"first")
            package_zip, _ = _make_package(run, tmp_path)
            out = tmp_path / "returns"
            kwargs = dict(
                source_run_value=run,
                package_id_value="fixture_package_v1",
                package_zip_value=package_zip,
                package_sha_value=_sha(package_zip.read_bytes()),
                report_value=report,
                coverage_value="",
                mentions_value="",
                unmapped_value="",
                summary_value="",
                out_dir_value=out,
            )
            import_chat_return(**kwargs)
            report.write_bytes(b"second")
            second = import_chat_return(**kwargs)
            self.assertEqual(second["status"], "REPORT_ONLY_ARCHIVED")
            versions = sorted(out.glob("report*.md"))
            self.assertEqual(len(versions), 2)
            self.assertEqual({path.read_bytes() for path in versions}, {b"first", b"second"})
            with self.assertRaises(HandoffError):
                import_chat_return(**{**kwargs, "package_sha_value": "0" * 64})
            with self.assertRaises(HandoffError):
                import_chat_return(**{**kwargs, "package_id_value": "../escape"})

            foreign_zip = tmp_path / "foreign.zip"
            with zipfile.ZipFile(package_zip) as source, zipfile.ZipFile(foreign_zip, "w", zipfile.ZIP_DEFLATED) as target:
                for name in source.namelist():
                    data = source.read(name)
                    if name == "manifest.json":
                        manifest = json.loads(data.decode("utf-8"))
                        manifest["package_id"] = "foreign_package_v1"
                        data = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                    target.writestr(name, data)
            with self.assertRaises(HandoffError):
                import_chat_return(**{
                    **kwargs,
                    "package_zip_value": foreign_zip,
                    "package_sha_value": _sha(foreign_zip.read_bytes()),
                })

    def test_import_preserves_invalid_structured_bytes_without_complete_status(self) -> None:
        with tempfile.TemporaryDirectory(prefix="chat_handoff_test_") as raw:
            tmp_path = Path(raw)
            run = _make_run(tmp_path)
            package_zip, _ = _make_package(run, tmp_path)
            report = tmp_path / "report.md"
            report.write_bytes(b"report")
            invalid = {}
            for name in ("coverage", "mentions", "unmapped", "summary"):
                path = tmp_path / f"{name}.{'json' if name == 'summary' else 'csv'}"
                path.write_bytes(b"garbage")
                invalid[name] = path
            kwargs = dict(
                source_run_value=run,
                package_id_value="fixture_package_v1",
                package_zip_value=package_zip,
                package_sha_value=_sha(package_zip.read_bytes()),
                report_value=report,
                coverage_value=invalid["coverage"],
                mentions_value=invalid["mentions"],
                unmapped_value=invalid["unmapped"],
                summary_value=invalid["summary"],
                out_dir_value=tmp_path / "returns",
            )
            receipt = import_chat_return(**kwargs)
            self.assertEqual(receipt["status"], "REPORT_AND_STRUCTURED_INVALID")
            self.assertEqual(receipt["structured_validation_status"], "INVALID")
            self.assertFalse(receipt["local_acceptance"]["structured_files_complete"])
            self.assertEqual(set(receipt["invalid_artifacts"]), {"coverage.csv", "mentions.csv", "unmapped.csv", "summary.json"})
            for key, path in invalid.items():
                archived = receipt["archived_files"][key]["archived_filename"]
                self.assertEqual((tmp_path / "returns" / archived).read_bytes(), b"garbage")
            repeat = import_chat_return(**kwargs)
            self.assertEqual(repeat["received_at"], receipt["received_at"])

    def test_import_rejects_same_identity_image_and_ocr_tampering(self) -> None:
        with tempfile.TemporaryDirectory(prefix="chat_handoff_test_") as raw:
            tmp_path = Path(raw)
            run = _make_run(tmp_path)
            package_zip, _ = _make_package(run, tmp_path)
            report = tmp_path / "report.md"
            report.write_bytes(b"report")
            base_kwargs = dict(
                source_run_value=run,
                package_id_value="fixture_package_v1",
                report_value=report,
                coverage_value="",
                mentions_value="",
                unmapped_value="",
                summary_value="",
                out_dir_value=tmp_path / "returns",
            )
            with zipfile.ZipFile(package_zip) as source:
                entries = {name: source.read(name) for name in source.namelist()}

            image_tampered = dict(entries)
            image_bytes = image_tampered["images/IMAGE001.jpg"] + b"same-identity-tamper"
            image_digest = _sha(image_bytes)
            image_tampered["images/IMAGE001.jpg"] = image_bytes
            rows = list(csv.DictReader(image_tampered["manifest.csv"].decode("utf-8-sig").splitlines()))
            fieldnames = list(rows[0])
            rows[0]["sha256"] = image_digest
            rows[0]["image_sha256"] = image_digest
            rows[0]["bytes"] = str(len(image_bytes))
            csv_buffer = io.StringIO(newline="")
            writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            image_tampered["manifest.csv"] = ("\ufeff" + csv_buffer.getvalue()).encode("utf-8")
            manifest = json.loads(image_tampered["manifest.json"].decode("utf-8"))
            manifest["manifest_sha256"] = _sha(image_tampered["manifest.csv"])
            manifest["images"][0]["sha256"] = image_digest
            manifest["images"][0]["bytes"] = len(image_bytes)
            image_tampered["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            image_zip = tmp_path / "same_identity_image_tampered.zip"
            _rewrite_zip(image_zip, image_tampered)
            with self.assertRaises(HandoffError):
                import_chat_return(**{
                    **base_kwargs,
                    "package_zip_value": image_zip,
                    "package_sha_value": _sha(image_zip.read_bytes()),
                })

            ocr_tampered = dict(entries)
            original_ocr = ocr_tampered["OCR_FULL.md"].decode("utf-8")
            tampered_ocr = original_ocr.replace("fixture OCR 1", "tampered OCR 1", 1)
            ocr_tampered["OCR_FULL.md"] = tampered_ocr.encode("utf-8")
            ocr_manifest = json.loads(ocr_tampered["manifest.json"].decode("utf-8"))
            ocr_manifest["images"][0]["ocr_text_sha256"] = _sha(b"tampered OCR 1")
            ocr_tampered["manifest.json"] = (json.dumps(ocr_manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            ocr_zip = tmp_path / "same_identity_ocr_tampered.zip"
            _rewrite_zip(ocr_zip, ocr_tampered)
            with self.assertRaises(HandoffError):
                import_chat_return(**{
                    **base_kwargs,
                    "package_zip_value": ocr_zip,
                    "package_sha_value": _sha(ocr_zip.read_bytes()),
                })
