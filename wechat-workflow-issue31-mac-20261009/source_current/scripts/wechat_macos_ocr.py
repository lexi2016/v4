# -*- coding: utf-8 -*-
"""macOS Vision OCR adapter with the Windows OCR artifact contract.

The shared runner keeps the historical ``windows_ocr_*`` filenames so coverage,
resume checks, and the validator remain backend-neutral.  Vision is compiled
at most once per invocation; that executable is launched separately for each
image or slice. Matching cached records do not initialize Vision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from wechat_common import validate_slice_geometry, ocr_record_complete

COMPILE_TIMEOUT_SECONDS = 60
OCR_TIMEOUT_SECONDS = 30
ENGINE = "macOS Vision Swift executable; one process per image/slice"


SWIFT_VISION_SOURCE = r'''
import Foundation
import Vision
import ImageIO
import CoreGraphics
import Darwin

func emit(_ value: [String: Any], code: Int32 = 0) -> Never {
    let data = try! JSONSerialization.data(withJSONObject: value, options: [])
    print(String(data: data, encoding: .utf8) ?? "{\"error\":\"json encode failed\"}")
    exit(code)
}

guard CommandLine.arguments.count >= 2 else {
    emit(["error": "image path required"], code: 2)
}
let path = CommandLine.arguments[1]
let url = URL(fileURLWithPath: path)
guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
    emit(["error": "unable to decode image", "path": path], code: 2)
}

var recognizedText = ""
var requestError = ""
let request = VNRecognizeTextRequest { request, error in
    if let error = error {
        requestError = error.localizedDescription
        return
    }
    let observations = (request.results as? [VNRecognizedTextObservation]) ?? []
    recognizedText = observations.compactMap { observation in
        observation.topCandidates(1).first?.string
    }.joined(separator: "\n")
}
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = true

do {
    let handler = VNImageRequestHandler(cgImage: image, options: [:])
    try handler.perform([request])
} catch {
    requestError = error.localizedDescription
}
if !requestError.isEmpty {
    emit(["error": requestError, "width": image.width, "height": image.height], code: 2)
}
emit(["text": recognizedText, "width": image.width, "height": image.height])
'''


def _ocr_config_sha256() -> str:
    # Legacy rows without this field remain reusable with explicit UNKNOWN
    # provenance; adding a field must not rerun a previously successful corpus.
    config = {"helper": SWIFT_VISION_SOURCE, "platform": sys.platform,
              "macos_version": platform.mac_ver()[0]}
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode("utf-8")).hexdigest()


def _normalize_result(result: dict) -> dict:
    result = dict(result)
    if result.get("status") == "OCR_OK" and not str(result.get("text") or "").strip():
        result.update(status="OCR_EMPTY", needs_visual_review=True)
    return result


def _terminal_empty(row: dict) -> bool:
    if row.get("status") not in {"OCR_EMPTY", "OCR_EMPTY_SLICED"}:
        return False
    parts = row.get("parts") or []
    if row["status"] == "OCR_EMPTY":
        return not parts and not str(row.get("text") or "").strip() and not row.get("error")
    if not isinstance(parts, list) or not parts:
        return False
    for n, part in enumerate(parts, 1):
        if not isinstance(part, dict) or part.get("part") != n or part.get("error"):
            return False
        expected = "OCR_OK" if str(part.get("text") or "").strip() else "OCR_EMPTY"
        if part.get("status") != expected:
            return False
    return (any(p["status"] == "OCR_EMPTY" for p in parts) and
            "\n".join(str(p.get("text") or "") for p in parts).strip() == str(row.get("text") or "").strip())


def _resolve_run_file(
    run_dir: Path,
    value: object,
    *,
    must_exist: bool = False,
    label: str = "run file",
) -> Path:
    """Resolve a run-owned file without following symlinks or escaping ``run_dir``."""

    run_dir = Path(run_dir).resolve()
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{label} path is missing")
    if "\x00" in raw:
        raise ValueError(f"{label} path contains NUL")
    lexical = Path(raw)
    if ".." in lexical.parts:
        raise ValueError(f"{label} path contains parent traversal")
    candidate = Path(os.path.abspath(str(lexical if lexical.is_absolute() else run_dir / lexical)))
    try:
        candidate.relative_to(run_dir)
    except ValueError as exc:
        raise ValueError(f"{label} is outside its permitted run directory") from exc

    current = candidate
    while True:
        if current.is_symlink():
            raise ValueError(f"{label} must not be a symlink")
        if current == run_dir:
            break
        if current.parent == current:
            raise ValueError(f"{label} is outside its permitted run directory")
        current = current.parent

    if candidate.exists():
        if not candidate.is_file():
            raise ValueError(f"{label} must be a regular file")
        return candidate
    if must_exist:
        raise ValueError(f"{label} does not exist")
    if not candidate.parent.is_dir() or candidate.parent.is_symlink():
        raise ValueError(f"{label} parent must be a regular directory")
    return candidate


def _atomic_write_bytes(path: Path, content: bytes, *, run_dir: Path) -> None:
    destination = _resolve_run_file(run_dir, path, label=f"output {Path(path).name}")
    if destination.is_file() and destination.read_bytes() == content:
        return
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        directory_fd = os.open(str(destination.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def _read_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, json.JSONDecodeError):
        return default


def _write_json(path: Path, value: object, *, run_dir: Path) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8-sig")
    _atomic_write_bytes(path, payload, run_dir=run_dir)


def _write_text(path: Path, value: str, *, run_dir: Path) -> None:
    _atomic_write_bytes(path, value.encode("utf-8-sig"), run_dir=run_dir)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _positive_index(value: object) -> int | None:
    try:
        index = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return index if index > 0 else None


def _resolve_regular_file(value: object, *, run_dir: Path, root: Path, label: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{label} path is missing")
    lexical = Path(raw)
    if ".." in lexical.parts:
        raise ValueError(f"{label} path contains parent traversal")
    if not lexical.is_absolute():
        lexical = run_dir / lexical
    lexical = Path(os.path.abspath(str(lexical)))

    current = lexical
    while True:
        if current.is_symlink():
            raise ValueError(f"{label} must not be a symlink")
        if current == run_dir or current.parent == current:
            break
        current = current.parent

    resolved = lexical.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"{label} must be a regular file")
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} is outside its permitted run directory") from exc
    return resolved


def _load_manifest_items(run_dir: Path, manifest: dict | None = None) -> dict[int, dict[str, object]]:
    run_dir = run_dir.resolve()
    if manifest is None:
        manifest_path = _resolve_run_file(
            run_dir,
            "ocr_slice_manifest.json",
            must_exist=True,
            label="slice manifest",
        )
        manifest = _read_json(manifest_path, {})
    if not isinstance(manifest, dict):
        raise RuntimeError("ocr_slice_manifest.json must be an object")
    try:
        image_count = int(manifest.get("image_count") or 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError("slice manifest image_count is invalid") from exc
    raw_images = manifest.get("images")
    if image_count < 0 or not isinstance(raw_images, list) or len(raw_images) != image_count:
        raise RuntimeError("slice manifest image count mismatch")

    image_root = run_dir / "wechat_article_images"
    if image_root.is_symlink() or not image_root.is_dir():
        raise RuntimeError("article image directory is invalid")
    slice_root = run_dir / "ocr_long_slices"
    items: dict[int, dict[str, object]] = {}
    seen_paths: set[Path] = set()
    for raw in raw_images:
        if not isinstance(raw, dict):
            raise RuntimeError("slice manifest image item is invalid")
        validate_slice_geometry(raw)
        index = _positive_index(raw.get("index"))
        if index is None or index in items:
            raise RuntimeError("slice manifest indexes are not one-to-one")
        image_path = _resolve_regular_file(
            raw.get("image_path"), run_dir=run_dir, root=image_root, label=f"image {index}"
        )
        if image_path in seen_paths:
            raise RuntimeError("slice manifest images refer to the same physical file")
        seen_paths.add(image_path)
        declared_sha = str(raw.get("image_sha256") or "").strip().lower()
        actual_sha = _sha256_file(image_path)
        image_stat = image_path.stat()
        image_snapshot = (
            image_path,
            actual_sha,
            (int(image_stat.st_dev), int(image_stat.st_ino), int(image_stat.st_size), int(image_stat.st_mtime_ns)),
        )
        image_sha_valid = bool(declared_sha) and declared_sha == actual_sha

        raw_parts = raw.get("parts")
        if raw_parts is None:
            raw_parts = []
        if not isinstance(raw_parts, list):
            raise RuntimeError(f"image {index} parts is invalid")
        parts: list[dict[str, object]] = []
        seen_parts: set[int] = set()
        parts_sha_valid = True
        for raw_part in raw_parts:
            if not isinstance(raw_part, dict):
                raise RuntimeError(f"image {index} part is invalid")
            part_number = _positive_index(raw_part.get("part"))
            if part_number is None or part_number in seen_parts:
                raise RuntimeError(f"image {index} part indexes are not one-to-one")
            seen_parts.add(part_number)
            part_path = _resolve_regular_file(
                raw_part.get("path"),
                run_dir=run_dir,
                root=slice_root,
                label=f"image {index} part {part_number}",
            )
            declared_part_sha = str(
                raw_part.get("sha256") or raw_part.get("image_sha256") or ""
            ).strip().lower()
            actual_part_sha = _sha256_file(part_path)
            part_stat = part_path.stat()
            part_snapshot = (
                part_path,
                actual_part_sha,
                (int(part_stat.st_dev), int(part_stat.st_ino), int(part_stat.st_size), int(part_stat.st_mtime_ns)),
            )
            part_sha_valid = bool(declared_part_sha) and declared_part_sha == actual_part_sha
            parts_sha_valid = parts_sha_valid and part_sha_valid
            parts.append(
                {
                    "part": part_number,
                    **{k: raw_part[k] for k in ("top", "bottom", "width", "height")},
                    "path": part_path,
                    "sha256": declared_part_sha,
                    "actual_sha256": actual_part_sha,
                    "source_snapshot": part_snapshot,
                    "source_valid": part_sha_valid,
                }
            )
        contiguous_parts = not seen_parts or seen_parts == set(range(1, max(seen_parts) + 1))
        source_valid = (
            image_sha_valid
            and parts_sha_valid
            and contiguous_parts
            and bool(raw.get("sliced")) == bool(parts)
        )
        ordered_parts = sorted(parts, key=lambda part: int(part["part"]))
        items[index] = {
            "index": index,
            "raw": raw,
            "path": image_path,
            "sha256": declared_sha,
            "actual_sha256": actual_sha,
            "source_snapshot": (
                image_snapshot,
                tuple(part.get("source_snapshot") for part in ordered_parts),
            ),
            "source_valid": source_valid,
            "width": int(raw.get("width") or 0),
            "height": int(raw.get("height") or 0),
            "parts": ordered_parts,
        }
    if set(items) != set(range(1, image_count + 1)):
        raise RuntimeError("slice manifest indexes are not one-to-one")
    return items


def _canary_indices(image_count: int) -> list[int]:
    count = int(image_count)
    if count < 1:
        return []
    middle = max(1, min(count, count // 2))
    return sorted({max(1, min(count, 2)), middle, count})


def _compile_vision_helper(temp_dir: Path) -> Path:
    executable = temp_dir / "wechat_vision_ocr"
    completed = subprocess.run(
        ["swiftc", "-O", "-framework", "Vision", "-framework", "ImageIO", "-framework", "CoreGraphics", "-o", str(executable), "-"],
        input=SWIFT_VISION_SOURCE,
        text=True,
        capture_output=True,
        encoding="utf-8",
        check=False,
        timeout=COMPILE_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "swiftc failed")[-4000:]
        raise RuntimeError(f"macOS Vision helper compile failed: {detail}")
    return executable


def _vision_ocr(executable: Path, image_path: Path) -> dict[str, object]:
    try:
        completed = subprocess.run(
            [str(executable), str(image_path)], text=True, capture_output=True,
            encoding="utf-8", check=False, timeout=OCR_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"status": "OCR_TIMEOUT", "text": "", "width": 0, "height": 0,
                "error": f"Vision call exceeded {OCR_TIMEOUT_SECONDS}s"}
    except OSError as exc:
        return {"status": "OCR_ERROR", "text": "", "width": 0, "height": 0,
                "error": str(exc)}
    raw = (completed.stdout or "").strip().splitlines()
    try:
        payload = json.loads(raw[-1]) if raw else {}
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict) or completed.returncode != 0 or payload.get("error"):
        error = str(payload.get("error") if isinstance(payload, dict) else "invalid Vision JSON")
        return {"status": "OCR_ERROR", "text": "", "width": 0, "height": 0,
                "error": error or (completed.stderr or "Vision OCR failed")[-4000:]}
    if "text" not in payload:
        return {"status": "OCR_ERROR", "text": "", "width": 0, "height": 0, "error": "Vision returned no text field"}
    try:
        width, height = int(payload.get("width") or 0), int(payload.get("height") or 0)
    except (TypeError, ValueError):
        return {"status": "OCR_ERROR", "text": "", "width": 0, "height": 0, "error": "invalid image dimensions"}
    return _normalize_result({"status": "OCR_OK", "text": str(payload["text"]),
                              "width": width, "height": height, "error": ""})


def _source_snapshot(
    value: object,
    *,
    expected_sha: object,
    run_dir: Path,
    root: Path,
    label: str,
) -> tuple[Path, str, tuple[int, int, int, int]]:
    """Re-check path, provenance, digest, and file identity around one OCR call."""

    try:
        path = _resolve_regular_file(value, run_dir=run_dir, root=root, label=label)
        actual_sha = _sha256_file(path)
        stat = path.stat()
    except (OSError, ValueError, TypeError) as error:
        raise RuntimeError(f"OCR source changed during processing: {label}") from error
    expected = str(expected_sha or "").strip().lower()
    if not expected or actual_sha != expected:
        raise RuntimeError(f"OCR source changed during processing: {label}")
    identity = (int(stat.st_dev), int(stat.st_ino), int(stat.st_size), int(stat.st_mtime_ns))
    return path, actual_sha, identity


def _assert_source_stable(
    before: tuple[Path, str, tuple[int, int, int, int]],
    after: tuple[Path, str, tuple[int, int, int, int]],
    *,
    label: str,
) -> None:
    if before != after:
        raise RuntimeError(f"OCR source changed during processing: {label}")


def _record_for_item(item: dict, name: str, executable: Path, *, run_dir: Path) -> dict[str, object]:
    image_before = _source_snapshot(
        item["image_path"],
        expected_sha=item.get("image_sha256"),
        run_dir=run_dir,
        root=run_dir / "wechat_article_images",
        label=f"image {item.get('index')}",
    )
    image_path, image_sha, _ = image_before
    if bool(item.get("sliced")):
        parts: list[dict[str, object]] = []
        for part in item.get("parts") or []:
            part_number = int(part.get("part") or len(parts) + 1)
            image_before = _source_snapshot(
                item["image_path"],
                expected_sha=image_sha,
                run_dir=run_dir,
                root=run_dir / "wechat_article_images",
                label=f"image {item.get('index')}",
            )
            part_before = _source_snapshot(
                part["path"],
                expected_sha=part.get("sha256"),
                run_dir=run_dir,
                root=run_dir / "ocr_long_slices",
                label=f"image {item.get('index')} part {part_number}",
            )
            part_path = part_before[0]
            try:
                result = _normalize_result(_vision_ocr(executable, part_path))
            finally:
                part_after = _source_snapshot(
                    part["path"],
                    expected_sha=part.get("sha256"),
                    run_dir=run_dir,
                    root=run_dir / "ocr_long_slices",
                    label=f"image {item.get('index')} part {part_number}",
                )
                image_after = _source_snapshot(
                    item["image_path"],
                    expected_sha=image_sha,
                    run_dir=run_dir,
                    root=run_dir / "wechat_article_images",
                    label=f"image {item.get('index')}",
                )
            _assert_source_stable(
                part_before,
                part_after,
                label=f"image {item.get('index')} part {part_number}",
            )
            _assert_source_stable(
                image_before,
                image_after,
                label=f"image {item.get('index')}",
            )
            parts.append({
                "part": part_number,
                "top": part["top"], "bottom": part["bottom"],
                "name": part_path.name,
                "path": str(part_path),
                "sha256": part_after[1],
                "status": result["status"],
                "text": result["text"],
                "width": result["width"],
                "height": result["height"],
                "error": result["error"],
            })
        text = "\n".join(str(part.get("text") or "") for part in parts).strip()
        statuses = {part.get("status") for part in parts}
        if "OCR_TIMEOUT" in statuses:
            status = "OCR_TIMEOUT_SLICED"
        elif statuses - {"OCR_OK", "OCR_EMPTY"}:
            status = "OCR_ERROR_SLICED"
        elif "OCR_EMPTY" in statuses:
            status = "OCR_EMPTY_SLICED"
        else:
            status = "OCR_OK_SLICED"
        errors = "; ".join(str(part.get("error") or "") for part in parts if part.get("error"))
        return {
            "index": int(item["index"]),
            "engine": ENGINE, "ocr_config_sha256": _ocr_config_sha256(),
            "needs_visual_review": status == "OCR_EMPTY_SLICED",
            "name": name,
            "path": str(image_path),
            "image_sha256": image_sha,
            "status": status,
            "text": text,
            "text_length": len(text),
            "width": int(item.get("width") or 0),
            "height": int(item.get("height") or 0),
            "parts": parts,
            "error": errors,
        }
    try:
        result = _normalize_result(_vision_ocr(executable, image_path))
    finally:
        image_after = _source_snapshot(
            item["image_path"],
            expected_sha=image_sha,
            run_dir=run_dir,
            root=run_dir / "wechat_article_images",
            label=f"image {item.get('index')}",
        )
    _assert_source_stable(image_before, image_after, label=f"image {item.get('index')}")
    text = str(result.get("text") or "")
    return {
        "index": int(item["index"]),
        "engine": ENGINE, "ocr_config_sha256": _ocr_config_sha256(),
        "needs_visual_review": result["status"] == "OCR_EMPTY",
        "name": name,
        "path": str(image_path),
        "image_sha256": image_sha,
        "status": result["status"],
        "text": text,
        "text_length": len(text),
        "width": int(result.get("width") or item.get("width") or 0),
        "height": int(result.get("height") or item.get("height") or 0),
        "parts": [],
        "error": str(result.get("error") or ""),
    }


def _normalized_manifest_item(item: dict, expected: dict[str, object]) -> dict[str, object]:
    normalized = dict(item)
    normalized["index"] = expected["index"]
    normalized["image_path"] = str(expected["path"])
    normalized["image_sha256"] = str(expected.get("sha256") or "")
    normalized["parts"] = [
        {
            **dict(part),
            "path": str(part["path"]),
            "sha256": str(part.get("sha256") or ""),
        }
        for part in expected.get("parts") or []
    ]
    return normalized


def _invalid_source_record(item: dict, expected: dict[str, object], name: str) -> dict[str, object]:
    parts = [
        {
            "part": int(part["part"]),
            "name": Path(str(part["path"])).name,
            "path": str(part["path"]),
            "sha256": str(part.get("sha256") or ""),
            "status": "OCR_ERROR",
            "text": "",
            "width": int(part.get("width") or 0),
            "height": int(part.get("height") or 0),
            "error": "source slice SHA256 does not match manifest",
        }
        for part in expected.get("parts") or []
    ]
    return {
        "index": int(expected["index"]),
        "name": name,
        "path": str(expected["path"]),
        "image_sha256": str(expected.get("sha256") or ""),
        "status": "OCR_ERROR_SLICED" if parts else "OCR_ERROR",
        "text": "",
        "text_length": 0,
        "width": int(item.get("width") or expected.get("width") or 0),
        "height": int(item.get("height") or expected.get("height") or 0),
        "parts": parts,
        "error": "source image or slice SHA256 does not match manifest",
    }


def _rows_from_json(value: object) -> list[dict]:
    rows = value if isinstance(value, list) else value.get("records", []) if isinstance(value, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _cache_row_matches(
    row: dict,
    expected: dict[str, object],
    *,
    run_dir: Path,
    allow_empty: bool = False,
) -> bool:
    if not bool(expected.get("source_valid")):
        return False
    if not ocr_record_complete(row) and not (allow_empty and _terminal_empty(row)):
        return False
    if row.get("ocr_config_sha256") and row["ocr_config_sha256"] != _ocr_config_sha256():
        return False

    expected_path = expected["path"]
    cached_path_text = str(row.get("path") or row.get("image_path") or "").strip()
    if cached_path_text != str(expected_path):
        return False
    try:
        cached_path = _resolve_regular_file(
            cached_path_text,
            run_dir=run_dir,
            root=run_dir / "wechat_article_images",
            label=f"cached image {expected['index']}",
        )
    except (OSError, ValueError, TypeError):
        return False
    expected_sha = str(expected.get("sha256") or "").lower()
    cached_sha = str(row.get("image_sha256") or "").strip().lower()
    if cached_path != expected_path or not expected_sha or cached_sha != expected_sha:
        return False
    for geometry_key in ("width", "height"):
        if row.get(geometry_key) != expected.get(geometry_key):
            return False
    try:
        if _sha256_file(cached_path) != expected_sha:
            return False
    except (OSError, ValueError):
        return False

    expected_parts = expected.get("parts") if isinstance(expected.get("parts"), list) else []
    raw_parts = row.get("parts")
    if raw_parts is None:
        raw_parts = []
    if not isinstance(raw_parts, list) or len(raw_parts) != len(expected_parts):
        return False
    expected_by_part = {
        int(part["part"]): part for part in expected_parts if isinstance(part, dict) and part.get("part") is not None
    }
    seen_parts: set[int] = set()
    for expected_number, raw_part in enumerate(raw_parts, 1):
        if not isinstance(raw_part, dict) or raw_part.get("part") != expected_number:
            return False
        part_number = _positive_index(raw_part.get("part"))
        if part_number is None or part_number in seen_parts or part_number not in expected_by_part:
            return False
        seen_parts.add(part_number)
        expected_part = expected_by_part[part_number]
        expected_part_path = expected_part["path"]
        cached_part_path_text = str(raw_part.get("path") or "").strip()
        if cached_part_path_text != str(expected_part_path):
            return False
        try:
            cached_part_path = _resolve_regular_file(
                cached_part_path_text,
                run_dir=run_dir,
                root=run_dir / "ocr_long_slices",
                label=f"cached image {expected['index']} part {part_number}",
            )
        except (OSError, ValueError, TypeError):
            return False
        expected_part_sha = str(expected_part.get("sha256") or "").lower()
        cached_part_sha = str(
            raw_part.get("sha256") or raw_part.get("image_sha256") or ""
        ).strip().lower()
        if cached_part_path != expected_part_path or not expected_part_sha or cached_part_sha != expected_part_sha:
            return False
        for geometry_key in ("top", "bottom", "width", "height"):
            if raw_part.get(geometry_key) != expected_part.get(geometry_key):
                return False
        try:
            if _sha256_file(cached_part_path) != expected_part_sha:
                return False
        except (OSError, ValueError):
            return False
    if seen_parts != set(expected_by_part):
        return False
    try:
        current_snapshot = _cache_row_source_snapshot(expected, run_dir=run_dir)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    return current_snapshot == expected.get("source_snapshot")


def _cache_row_source_snapshot(
    expected: dict[str, object],
    *,
    run_dir: Path,
) -> tuple[
    tuple[Path, str, tuple[int, int, int, int]],
    tuple[tuple[Path, str, tuple[int, int, int, int]], ...],
]:
    """Capture the source provenance used by one cached OCR row."""

    image_snapshot = _source_snapshot(
        expected["path"],
        expected_sha=expected.get("sha256"),
        run_dir=run_dir,
        root=run_dir / "wechat_article_images",
        label=f"image {expected.get('index')}",
    )
    part_snapshots = tuple(
        _source_snapshot(
            part["path"],
            expected_sha=part.get("sha256"),
            run_dir=run_dir,
            root=run_dir / "ocr_long_slices",
            label=f"image {expected.get('index')} part {part.get('part')}",
        )
        for part in (expected.get("parts") or [])
        if isinstance(part, dict)
    )
    return image_snapshot, part_snapshots


def _existing_ok_rows(
    rows: list[dict],
    expected_sha: dict[int, str] | None,
    manifest_items: dict[int, dict[str, object]],
    run_dir: Path,
    *, allow_empty: bool = False,
) -> dict[int, dict]:
    reusable: dict[int, dict] = {}
    duplicate_indices: set[int] = set()
    for row in rows:
        try:
            index = int(row.get("index") or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        if index in reusable or index in duplicate_indices:
            duplicate_indices.add(index)
            reusable.pop(index, None)
            continue
        expected = manifest_items.get(index)
        if expected is None:
            continue
        if expected_sha is not None and str(expected_sha.get(index) or "").strip().lower() != str(expected.get("sha256") or "").lower():
            continue
        if _cache_row_matches(row, expected, run_dir=run_dir, allow_empty=allow_empty):
            reusable[index] = row
    return reusable


def _reuse_cached_rows(
    records_by_index: dict[int, dict],
    rows: dict[int, dict],
    manifest_items: dict[int, dict[str, object]],
    run_dir: Path,
) -> None:
    """Copy cache rows only across a source-stable reuse boundary."""

    before: dict[int, object] = {}
    for index in rows:
        expected = manifest_items.get(index)
        if expected is None:
            raise RuntimeError(f"OCR cache item {index} is no longer available")
        try:
            snapshot = _cache_row_source_snapshot(expected, run_dir=run_dir)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise RuntimeError(f"OCR source changed during cache reuse: image {index}") from error
        if snapshot != expected.get("source_snapshot"):
            raise RuntimeError(f"OCR source changed during cache reuse: image {index}")
        before[index] = snapshot

    records_by_index.update(rows)
    for index, previous in before.items():
        expected = manifest_items[index]
        try:
            current = _cache_row_source_snapshot(expected, run_dir=run_dir)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            records_by_index.pop(index, None)
            raise RuntimeError(f"OCR source changed during cache reuse: image {index}") from error
        if current != previous:
            records_by_index.pop(index, None)
            raise RuntimeError(f"OCR source changed during cache reuse: image {index}")


def _existing_ok(
    path: Path,
    expected_sha: dict[int, str] | None = None,
    manifest_items: dict[int, dict[str, object]] | None = None,
    run_dir: Path | None = None,
    *, allow_empty: bool = False,
) -> dict[int, dict]:
    if run_dir is not None:
        path = _resolve_run_file(run_dir, path, label="OCR checkpoint")
    value = _read_json(path, [])
    rows = _rows_from_json(value)
    if manifest_items is not None:
        if run_dir is None:
            raise ValueError("run_dir is required for provenance-checked OCR cache reuse")
        return _existing_ok_rows(
            rows,
            expected_sha,
            manifest_items,
            run_dir.resolve(),
            allow_empty=allow_empty,
        )
    return {
        int(row["index"]): row
        for row in rows
        if str(row.get("status", "")).startswith("OCR_OK")
        and str(row.get("text") or "").strip()
        and str(row.get("image_sha256") or "")
        and (
            expected_sha is None
            or str(row.get("image_sha256") or "") == str(expected_sha.get(int(row.get("index") or 0)) or "")
        )
    }


def _summary(records: list[dict], mode: str, image_count: int, planned_indices: list[int] | None = None) -> dict[str, object]:
    ok = sum(ocr_record_complete(row) for row in records)
    timeouts = sum("TIMEOUT" in str(row.get("status", "")) or any("TIMEOUT" in str(p.get("status", "")) for p in (row.get("parts") or [])) for row in records)
    empty = sum("EMPTY" in str(row.get("status", "")) or
                (str(row.get("status", "")).startswith("OCR_OK") and not ocr_record_complete(row) and
                 (not str(row.get("text") or "").strip() or any(not str(p.get("text") or "").strip() for p in (row.get("parts") or []))))
                for row in records)
    errors = sum(not ocr_record_complete(row) and "TIMEOUT" not in str(row.get("status", "")) and
                 "EMPTY" not in str(row.get("status", "")) for row in records)
    expected_count = image_count if mode == "Full" else len(planned_indices or [])
    result: dict[str, object] = {
        "status": "OCR_NOT_APPLICABLE" if image_count == 0 else ("OCR_OK" if ok == expected_count and len(records) == expected_count else "OCR_PARTIAL"),
        "mode": mode, "image_count": expected_count, "ocr_applicable": image_count > 0,
        "body_source_required": image_count == 0, "processed_count": len(records),
        "ok_count": ok, "timeout_count": timeouts, "error_count": errors,
        "empty_count": empty, "text_length": sum(len(str(row.get("text") or "")) for row in records),
        "strategy": "macos_vision_compiled_once_process_per_image_or_slice",
        "engine": ENGINE, "ocr_config_sha256": _ocr_config_sha256(),
        "legacy_config_unknown_count": sum(not bool(r.get("ocr_config_sha256")) for r in records),
        "max_image_dimension": 10000, "compile_timeout_seconds": COMPILE_TIMEOUT_SECONDS,
        "ocr_timeout_seconds": OCR_TIMEOUT_SECONDS,
    }
    if mode == "Canary":
        result["planned_indices"] = planned_indices or []
    return result


def run(mode: str, run_dir: Path, *, retry_empty: bool = False) -> dict[str, object]:
    run_dir = run_dir.resolve()
    fixed_paths = {
        name: _resolve_run_file(run_dir, name, label=f"OCR path {name}")
        for name in (
            "ocr_slice_manifest.json",
            "windows_ocr_checkpoint.json",
            "windows_ocr_canary.json",
            "windows_ocr_canary_summary.json",
            "windows_ocr_results.json",
            "wechat_article_ocr_summary.json",
            "windows_ocr_results.md",
            "wechat_article_ocr_text.txt",
        )
    }
    manifest = _read_json(fixed_paths["ocr_slice_manifest.json"], {})
    if not isinstance(manifest, dict):
        raise RuntimeError("ocr_slice_manifest.json must be an object")
    items = _load_manifest_items(run_dir, manifest)
    image_count = len(items)
    checkpoint_path = fixed_paths["windows_ocr_checkpoint.json"]
    expected_sha = {index: str(item.get("sha256") or "") for index, item in items.items()}
    existing: dict[int, dict] = {}
    # Prefer the newest durable checkpoint; only fill missing indices from
    # completed results/canary. Empty observations are terminal, not success.
    for cache_path in (checkpoint_path, fixed_paths["windows_ocr_results.json"], fixed_paths["windows_ocr_canary.json"]):
        rows = _existing_ok(cache_path, expected_sha, manifest_items=items, run_dir=run_dir,
                            allow_empty=not retry_empty)
        for index, row in rows.items():
            existing.setdefault(index, row)
    targets = _canary_indices(image_count) if mode == "Canary" else list(range(1, image_count + 1))
    existing = {index: row for index, row in existing.items() if index in targets}
    records_by_index: dict[int, dict] = {}
    _reuse_cached_rows(records_by_index, existing, items, run_dir)
    pending = [index for index in targets if index not in existing]
    needs_vision = any(bool(items[index].get("source_valid")) for index in pending)

    def process_pending(executable: Path | None) -> None:
        for index in pending:
            expected = items.get(index)
            if expected is None:
                raise RuntimeError(f"Missing slice manifest item for image {index}")
            item = expected.get("raw") if isinstance(expected.get("raw"), dict) else {}
            if not bool(expected.get("source_valid")):
                record = _invalid_source_record(item, expected, f"img_{index:02d}.jpg")
            else:
                if executable is None:
                    raise RuntimeError("Vision helper is required for a valid OCR source")
                record = _record_for_item(
                    _normalized_manifest_item(item, expected),
                    f"img_{index:02d}.jpg",
                    executable,
                    run_dir=run_dir,
                )
            records_by_index[index] = record
            if mode == "Full":
                _write_json(
                    checkpoint_path,
                    [records_by_index[key] for key in sorted(records_by_index)],
                    run_dir=run_dir,
                )

    if needs_vision:
        with tempfile.TemporaryDirectory(prefix="wechat_vision_ocr_") as temp:
            try:
                executable = _compile_vision_helper(Path(temp))
            except (subprocess.TimeoutExpired, RuntimeError, OSError) as exc:
                status = "OCR_TIMEOUT" if isinstance(exc, subprocess.TimeoutExpired) else "OCR_ERROR"
                for index in pending:
                    expected = items[index]
                    record = _invalid_source_record(expected["raw"], expected, Path(str(expected["path"])).name)
                    record.update(status=status, error=f"helper setup: {str(exc)[:2000]}",
                                  engine=ENGINE, ocr_config_sha256=_ocr_config_sha256())
                    for part in record["parts"]:
                        part.update(status=status, error=record["error"])
                    records_by_index[index] = record
                if mode == "Full":
                    _write_json(checkpoint_path, [records_by_index[k] for k in sorted(records_by_index)], run_dir=run_dir)
            else:
                process_pending(executable)
    else:
        process_pending(None)

    records = [records_by_index[key] for key in sorted(records_by_index)]
    if mode == "Canary":
        json_path = fixed_paths["windows_ocr_canary.json"]
        summary_path = fixed_paths["windows_ocr_canary_summary.json"]
    else:
        json_path = fixed_paths["windows_ocr_results.json"]
        summary_path = fixed_paths["wechat_article_ocr_summary.json"]
    _write_json(json_path, records, run_dir=run_dir)
    summary = _summary(records, mode, image_count, targets)
    summary.update(cache_reused_count=len(existing), attempted_count=len(pending),
                   empty_deferred_count=sum(_terminal_empty(r) for r in existing.values()))
    _write_json(summary_path, summary, run_dir=run_dir)

    if mode == "Full":
        blocks = [f"=====IMAGE{int(row['index']):03d} {row['name']} [{row['status']}]=====\n{row.get('text', '')}" for row in records]
        _write_text(fixed_paths["windows_ocr_results.md"], "\n\n".join(blocks), run_dir=run_dir)
        _write_text(fixed_paths["wechat_article_ocr_text.txt"], "\n\n".join(blocks), run_dir=run_dir)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="macOS Vision OCR adapter")
    parser.add_argument("--mode", choices=["Canary", "Full"], required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--retry-empty", action="store_true", help="Explicitly retry terminal empty observations; default preserves them for visual review")
    args = parser.parse_args(argv)
    summary = run(args.mode, Path(args.run_dir), retry_empty=args.retry_empty)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] in {"OCR_OK", "OCR_NOT_APPLICABLE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
