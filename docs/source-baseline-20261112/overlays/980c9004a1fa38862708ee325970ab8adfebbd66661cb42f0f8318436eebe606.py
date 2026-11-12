# -*- coding: utf-8 -*-
"""Prepare OCR slices for a run: sha256 + long-image slicing -> ocr_slice_manifest.json.

Direct translation of codex_prepare_ocr.py, parameterized by --run-dir.
Shared script lives in scripts/ and is NOT copied into run dirs.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path

import argparse
import sys
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wechat_common import safe_run_path, validate_run_dir, validate_slice_geometry  # noqa: E402

MAX_DIMENSION = 10_000
SLICE_HEIGHT = 9_000
DEFAULT_MANIFEST_FIELDS = [
    "idx",
    "url",
    "local_path",
    "download_status",
    "image_size",
    "ocr_text_length",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_size(path: Path) -> tuple[int, int]:
    """Read dimensions with Pillow when available, then macOS sips."""

    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as image:
            return int(image.size[0]), int(image.size[1])
    except (ImportError, OSError, ValueError):
        completed = subprocess.run(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
            capture_output=True, text=True, check=False, timeout=60,
        )
        values = dict(re.findall(r"pixel(Width|Height):\s*(\d+)", completed.stdout or "", re.IGNORECASE))
        if set(values) == {"Width", "Height"}:
            return int(values["Width"]), int(values["Height"])
        raise RuntimeError(f"cannot read image dimensions: {path}")


def _crop_image(path: Path, output: Path, *, width: int, top: int, height: int) -> None:
    """Crop a long image with Pillow or the native macOS ImageIO tool."""

    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as image:
            image.crop((0, top, width, top + height)).save(output, format="PNG")
        return
    except (ImportError, OSError, ValueError):
        pass
    completed = subprocess.run(
        [
            "sips", "--cropToHeightWidth", str(height), str(width),
            "--cropOffset", str(top), "0", str(path), "--out", str(output),
        ],
        capture_output=True, text=True, check=False, timeout=60,
    )
    if completed.returncode != 0 or not output.is_file():
        raise RuntimeError(f"cannot crop long image without an image backend: {path}")


def _run_artifact(run: Path, value: object, *, label: str, must_exist: bool = False) -> Path:
    """Resolve collector paths that may be module-relative (runs/<id>/...)."""

    raw = Path(str(value or "").strip())
    if not raw.is_absolute():
        parts = raw.parts
        if len(parts) >= 2 and parts[0] == "runs" and parts[1] == run.name:
            raw = Path(*parts[2:])
        elif parts and parts[0] == run.name:
            raw = Path(*parts[1:])
    return safe_run_path(run, raw, must_exist=must_exist, label=label)


def _write_if_changed(path: Path, data: bytes) -> None:
    """Do not rewrite identical artifacts (including their modification time)."""
    if path.is_file() and path.read_bytes() == data:
        return
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_image_manifest(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    _write_if_changed(path, buffer.getvalue().encode("utf-8-sig"))


def _cached_parts(run: Path, item: dict[str, object], digest: str, width: int, height: int) -> dict[int, dict]:
    """Reuse only geometry from an unchanged source; each file is checked separately."""
    if item.get("image_sha256") != digest or (item.get("width"), item.get("height")) != (width, height):
        return {}
    try:
        validate_slice_geometry(item)
    except (ValueError, TypeError, KeyError):
        return {}
    return {part["part"]: part for part in item.get("parts", [])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare OCR slices for a run.")
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args(argv)

    # Windows.Media.Ocr's WinRT StorageFile API requires an absolute path;
    # callers commonly pass ``runs/<id>`` relative to the module root.
    run = validate_run_dir(args.run_dir)
    image_dir = safe_run_path(run, "wechat_article_images", must_exist=True, label="image directory")
    slice_dir = safe_run_path(run, "ocr_long_slices", label="OCR slice directory")
    if slice_dir.exists() and not slice_dir.is_dir():
        raise ValueError(f"OCR slice path is not a directory: {slice_dir}")
    intake_path = safe_run_path(run, "wechat_article_intake_summary.json", label="intake summary")
    manifest_path = safe_run_path(run, "wechat_article_image_manifest.csv", must_exist=True, label="image manifest")

    # Intake is immutable provenance here; do not rewrite collector path fields.
    output_manifest = safe_run_path(run, "ocr_slice_manifest.json", label="OCR slice manifest")
    cached_images: dict[int, dict] = {}
    if output_manifest.is_file():
        try:
            prior = json.loads(output_manifest.read_text(encoding="utf-8-sig"))
            if prior.get("max_dimension") == MAX_DIMENSION and prior.get("slice_height") == SLICE_HEIGHT:
                cached_images = {item["index"]: item for item in prior.get("images", [])}
        except (ValueError, KeyError, TypeError, AttributeError):
            cached_images = {}

    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        manifest_fields = list(reader.fieldnames or [])
        if any(not isinstance(field, str) or not field for field in manifest_fields):
            raise ValueError("image manifest header contains an empty field")
        rows = list(reader)
        if len(set(manifest_fields)) != len(manifest_fields) or any(None in row or any(value is None for value in row.values()) for row in rows):
            raise ValueError("image manifest has duplicated columns or malformed rows")

    slice_manifest: list[dict[str, object]] = []
    slice_dir.mkdir(parents=True, exist_ok=True)
    seen_indices: set[int] = set()
    for row in rows:
        try:
            idx = int(row["idx"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("image manifest index is invalid") from exc
        if idx <= 0 or idx in seen_indices:
            raise ValueError("image manifest index is missing or duplicated")
        seen_indices.add(idx)
        declared_path = str(row.get("local_path") or "").strip()
        if declared_path:
            image_path = _run_artifact(run, declared_path, must_exist=True, label=f"image {idx}")
        else:
            image_path = None
            for suffix in (".jpg", ".jpeg", ".png", ".webp"):
                candidate = safe_run_path(run, f"wechat_article_images/img_{idx:02d}{suffix}", label=f"image {idx}")
                if candidate.is_file():
                    image_path = candidate
                    break
            if image_path is None:
                raise FileNotFoundError(f"image {idx} is missing")
        if image_path.parent != image_dir.resolve():
            raise ValueError(f"image {idx} is outside the article image directory")
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        digest = sha256(image_path)
        for hash_field in ("image_sha256", "sha256"):
            declared = str(row.get(hash_field) or "").strip()
            if declared and declared.lower() != digest:
                raise ValueError(f"image {idx} {hash_field} differs from source bytes")
        width, height = _image_size(image_path)
        old_item = cached_images.get(idx, {})
        reusable_parts = _cached_parts(run, old_item, digest, width, height)
        row["local_path"] = str(image_path)
        row["download_status"] = f"OK bytes={image_path.stat().st_size}"
        row["image_size"] = f"{width}x{height}"
        if old_item and old_item.get("image_sha256") != digest:
            row["ocr_text_length"] = ""
        else:
            row.setdefault("ocr_text_length", "")
        parts: list[dict[str, object]] = []
        if max(width, height) > MAX_DIMENSION:
            if width > MAX_DIMENSION:
                raise RuntimeError(f"horizontal slicing not implemented for {image_path.name}: {width}x{height}")
            part_number = 0
            for top in range(0, height, SLICE_HEIGHT):
                part_number += 1
                bottom = min(top + SLICE_HEIGHT, height)
                part_path = safe_run_path(
                    run,
                    f"ocr_long_slices/img_{idx:02d}_part_{part_number:02d}.png",
                    label=f"OCR slice {idx}",
                )
                cached_part = reusable_parts.get(part_number, {})
                reuse = False
                if cached_part and (cached_part.get("top"), cached_part.get("bottom")) == (top, bottom):
                    try:
                        old_path = _run_artifact(run, cached_part.get("path"), label="cached slice", must_exist=True)
                        reuse = old_path == part_path and sha256(old_path) == cached_part.get("sha256")
                    except (ValueError, FileNotFoundError):
                        pass
                if not reuse:
                    _crop_image(image_path, part_path, width=width, top=top, height=bottom - top)
                parts.append({
                    "part": part_number,
                    "path": str(part_path),
                    "top": top,
                    "bottom": bottom,
                    "width": width,
                    "height": bottom - top,
                    "sha256": sha256(part_path),
                })
        slice_manifest.append({
            "index": idx,
            "image_path": str(image_path),
            "image_sha256": digest,
            "width": width,
            "height": height,
            "sliced": bool(parts),
            "parts": parts,
        })

    fields = list(dict.fromkeys(manifest_fields + DEFAULT_MANIFEST_FIELDS))
    _write_image_manifest(manifest_path, rows, fields)

    output_manifest = safe_run_path(run, "ocr_slice_manifest.json", label="OCR slice manifest")
    output = {
        "status": "PREPARED",
        "max_dimension": MAX_DIMENSION,
        "slice_height": SLICE_HEIGHT,
        "image_count": len(rows),
        "sliced_image_count": sum(1 for item in slice_manifest if item["sliced"]),
        "images": slice_manifest,
    }
    _write_if_changed(output_manifest, json.dumps(output, ensure_ascii=False, indent=2).encode("utf-8-sig"))
    print(json.dumps({
        "status": "PREPARED",
        "run_dir": str(run),
        "image_count": len(rows),
        "sliced_image_count": sum(1 for item in slice_manifest if item["sliced"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
