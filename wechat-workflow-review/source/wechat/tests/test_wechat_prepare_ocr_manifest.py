from __future__ import annotations

import base64
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "wechat_prepare_ocr.py"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
BASE_FIELDS = [
    "idx",
    "url",
    "local_path",
    "download_status",
    "image_size",
    "ocr_text_length",
]
EXTENDED_FIELDS = BASE_FIELDS + [
    "image_sha256",
    "sha256",
    "bytes",
    "attempts",
    "cache_status",
    "content_type",
    "error",
]


def _write_manifest(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _run_prepare(run_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--run-dir", str(run_dir)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _make_run(tmp_path: Path, fields: list[str]) -> tuple[Path, list[dict[str, str]]]:
    run = tmp_path / "run"
    image_dir = run / "wechat_article_images"
    image_dir.mkdir(parents=True)
    rows: list[dict[str, str]] = []
    for index in (1, 2):
        image = image_dir / f"img_{index:02d}.png"
        image.write_bytes(PNG_1X1)
        image_sha = hashlib.sha256(PNG_1X1).hexdigest()
        row = {
            "idx": str(index),
            "url": f"https://mmbiz.qpic.cn/example/{index}",
            "local_path": str(image),
            "download_status": f"OK bytes={len(PNG_1X1)}",
            "image_size": "",
            "ocr_text_length": "",
            "image_sha256": image_sha,
            "sha256": image_sha,
            "bytes": str(len(PNG_1X1)),
            "attempts": "1",
            "cache_status": "DOWNLOADED" if index == 1 else "REUSED",
            "content_type": "image/png",
            "error": "",
        }
        rows.append({field: row.get(field, "") for field in fields})
    _write_manifest(run / "wechat_article_image_manifest.csv", fields, rows)
    return run, rows


def _read_manifest(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def test_prepare_preserves_legacy_six_column_manifest(tmp_path: Path) -> None:
    run, _ = _make_run(tmp_path, BASE_FIELDS)

    result = _run_prepare(run)

    assert result.returncode == 0, result.stderr
    fields, rows = _read_manifest(run / "wechat_article_image_manifest.csv")
    assert fields == BASE_FIELDS
    assert [row["idx"] for row in rows] == ["1", "2"]
    assert json.loads((run / "ocr_slice_manifest.json").read_text(encoding="utf-8-sig"))["image_count"] == 2


def test_prepare_preserves_extended_provenance_and_is_idempotent(tmp_path: Path) -> None:
    run, original_rows = _make_run(tmp_path, EXTENDED_FIELDS)
    manifest = run / "wechat_article_image_manifest.csv"

    first = _run_prepare(run)
    assert first.returncode == 0, first.stderr
    first_fields, first_rows = _read_manifest(manifest)
    assert first_fields == EXTENDED_FIELDS
    for original, actual in zip(original_rows, first_rows):
        assert actual["idx"] == original["idx"]
        assert actual["url"] == original["url"]
        assert Path(actual["local_path"]).resolve() == Path(original["local_path"]).resolve()
        for field in ("image_sha256", "sha256", "bytes", "attempts", "cache_status", "content_type", "error"):
            assert actual[field] == original[field]
        assert actual["image_size"] == "1x1"
        assert actual["ocr_text_length"] == ""

    first_manifest_bytes = manifest.read_bytes()
    first_slice_bytes = (run / "ocr_slice_manifest.json").read_bytes()
    second = _run_prepare(run)
    assert second.returncode == 0, second.stderr
    assert manifest.read_bytes() == first_manifest_bytes
    assert (run / "ocr_slice_manifest.json").read_bytes() == first_slice_bytes
