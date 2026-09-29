from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _make_run(
    root: Path,
    *,
    image_bytes: bytes = b"image-v1",
    declared_image_sha: str | None = None,
    cache_path: str | None = None,
    cache_sha: str | None = None,
    sliced: bool = False,
    cache_parts: list[dict[str, object]] | None = None,
) -> tuple[Path, Path, str]:
    run = root / "run"
    image_dir = run / "wechat_article_images"
    image_dir.mkdir(parents=True)
    image = image_dir / "img_01.jpg"
    image.write_bytes(image_bytes)
    actual_image_sha = _sha256(image)
    declared_image_sha = declared_image_sha or actual_image_sha

    manifest_parts: list[dict[str, object]] = []
    if sliced:
        slice_dir = run / "ocr_long_slices"
        slice_dir.mkdir()
        part = slice_dir / "img_01_part_01.png"
        part.write_bytes(b"part-v1")
        manifest_parts.append(
            {
                "part": 1,
                "path": str(part),
                "sha256": _sha256(part),
                "top": 0, "bottom": 1, "width": 1, "height": 1,
            }
        )

    _write_json(
        run / "ocr_slice_manifest.json",
        {
            "status": "PREPARED",
            "image_count": 1,
            "images": [
                {
                    "index": 1,
                    "image_path": str(image),
                    "image_sha256": declared_image_sha,
                    "width": 1,
                    "height": 1,
                    "sliced": sliced,
                    "parts": manifest_parts,
                }
            ],
        },
    )

    row_path = cache_path or str(image)
    row_sha = cache_sha or declared_image_sha
    cache_row = {
        "index": 1,
        "name": "img_01.jpg",
        "path": row_path,
        "image_sha256": row_sha,
        "width": 1,
        "height": 1,
        "status": "OCR_OK" if not sliced else "OCR_OK_SLICED",
        "text": "cached text",
        "text_length": 11,
        "parts": cache_parts if cache_parts is not None else [dict(part, status="OCR_OK", text="cached text", error="") for part in manifest_parts],
    }
    _write_json(run / "windows_ocr_checkpoint.json", [cache_row])
    return run, image, actual_image_sha


def test_matching_cache_is_reused_without_compile_or_ocr(tmp_path: Path) -> None:
    adapter = importlib.import_module("wechat_macos_ocr")
    run, _, _ = _make_run(tmp_path)

    with patch.object(adapter, "_compile_vision_helper", side_effect=AssertionError("compile")) as compile_helper:
        with patch.object(adapter, "_vision_ocr", side_effect=AssertionError("ocr")) as vision_ocr:
            summary = adapter.run("Full", run)

    assert summary["status"] == "OCR_OK"
    compile_helper.assert_not_called()
    vision_ocr.assert_not_called()


def test_cache_rejects_changed_bytes_with_old_declared_sha(tmp_path: Path) -> None:
    adapter = importlib.import_module("wechat_macos_ocr")
    old_sha = hashlib.sha256(b"image-v1").hexdigest()
    run, _, _ = _make_run(tmp_path, image_bytes=b"image-v2", declared_image_sha=old_sha)

    items = adapter._load_manifest_items(run)
    assert adapter._existing_ok(
        run / "windows_ocr_checkpoint.json",
        {1: old_sha},
        manifest_items=items,
        run_dir=run,
    ) == {}


@pytest.mark.parametrize("geometry_key", ["width", "height"])
def test_cache_rejects_changed_image_geometry(tmp_path: Path, geometry_key: str) -> None:
    adapter = importlib.import_module("wechat_macos_ocr")
    run, _, image_sha = _make_run(tmp_path)
    checkpoint = run / "windows_ocr_checkpoint.json"
    rows = json.loads(checkpoint.read_text())
    rows[0][geometry_key] = 999
    _write_json(checkpoint, rows)
    items = adapter._load_manifest_items(run)
    assert adapter._existing_ok(checkpoint, {1: image_sha}, items, run) == {}


@pytest.mark.parametrize("geometry_key", ["top", "bottom", "width", "height"])
def test_cache_rejects_changed_slice_geometry(tmp_path: Path, geometry_key: str) -> None:
    adapter = importlib.import_module("wechat_macos_ocr")
    run, _, image_sha = _make_run(tmp_path, sliced=True)
    checkpoint = run / "windows_ocr_checkpoint.json"
    rows = json.loads(checkpoint.read_text())
    rows[0]["parts"][0][geometry_key] = 999
    _write_json(checkpoint, rows)
    items = adapter._load_manifest_items(run)
    assert adapter._existing_ok(checkpoint, {1: image_sha}, items, run) == {}


def test_cache_rejects_wrong_path_and_out_of_root_path(tmp_path: Path) -> None:
    adapter = importlib.import_module("wechat_macos_ocr")
    run, image, image_sha = _make_run(tmp_path)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(image.read_bytes())

    for bad_path in (str(run / "wechat_article_images" / "other.jpg"), str(outside)):
        _write_json(
            run / "windows_ocr_checkpoint.json",
            [{
                "index": 1,
                "path": bad_path,
                "image_sha256": image_sha,
                "status": "OCR_OK",
                "text": "cached text",
                "parts": [],
            }],
        )
        items = adapter._load_manifest_items(run)
        assert adapter._existing_ok(
            run / "windows_ocr_checkpoint.json",
            {1: image_sha},
            manifest_items=items,
            run_dir=run,
        ) == {}


def test_cache_rejects_symlink_and_sliced_part_mismatch(tmp_path: Path) -> None:
    adapter = importlib.import_module("wechat_macos_ocr")
    run, image, image_sha = _make_run(tmp_path, sliced=True)
    link = run / "wechat_article_images" / "img_01_link.jpg"
    link.symlink_to(image)
    part = run / "ocr_long_slices" / "img_01_part_01.png"
    stale_part_sha = "0" * 64

    for cached_path, cached_parts in (
        (str(link), [{"part": 1, "path": str(part), "sha256": _sha256(part)}]),
        (str(image), [{"part": 1, "path": str(part), "sha256": stale_part_sha}]),
    ):
        _write_json(
            run / "windows_ocr_checkpoint.json",
            [{
                "index": 1,
                "path": cached_path,
                "image_sha256": image_sha,
                "status": "OCR_OK_SLICED",
                "text": "cached text",
                "parts": cached_parts,
            }],
        )
        items = adapter._load_manifest_items(run)
        assert adapter._existing_ok(
            run / "windows_ocr_checkpoint.json",
            {1: image_sha},
            manifest_items=items,
            run_dir=run,
        ) == {}


def test_fixed_ocr_paths_reject_existing_symlinks_before_vision(tmp_path: Path) -> None:
    adapter = importlib.import_module("wechat_macos_ocr")
    cases = {
        "windows_ocr_checkpoint.json": "Full",
        "windows_ocr_canary.json": "Canary",
        "windows_ocr_canary_summary.json": "Canary",
        "windows_ocr_results.json": "Full",
        "wechat_article_ocr_summary.json": "Full",
        "windows_ocr_results.md": "Full",
        "wechat_article_ocr_text.txt": "Full",
    }
    for output_name, mode in cases.items():
        case_root = tmp_path / output_name.replace(".", "-")
        run, _, _ = _make_run(case_root)
        outside = case_root / "outside-output"
        outside.write_text("outside", encoding="utf-8")
        output_path = run / output_name
        output_path.unlink(missing_ok=True)
        output_path.symlink_to(outside)
        with patch.object(adapter, "_compile_vision_helper", side_effect=AssertionError("compile")):
            with patch.object(adapter, "_vision_ocr", side_effect=AssertionError("ocr")):
                with pytest.raises(ValueError, match="symlink|regular"):
                    adapter.run(mode, run)


def test_fixed_ocr_paths_reject_nonregular_and_symlink_ancestors(tmp_path: Path) -> None:
    adapter = importlib.import_module("wechat_macos_ocr")
    run, _, _ = _make_run(tmp_path / "nonregular")
    output_path = run / "windows_ocr_results.json"
    output_path.unlink(missing_ok=True)
    output_path.mkdir()
    with pytest.raises(ValueError, match="regular"):
        adapter.run("Full", run)

    ancestor_root = tmp_path / "ancestor"
    ancestor_run, _, _ = _make_run(ancestor_root)
    outside = ancestor_root / "outside-dir"
    outside.mkdir()
    unsafe_parent = ancestor_run / "unsafe-parent"
    unsafe_parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink|run directory"):
        adapter._resolve_run_file(ancestor_run, "unsafe-parent/result.json")


def test_fixed_ocr_outputs_use_same_directory_atomic_replacement(tmp_path: Path) -> None:
    adapter = importlib.import_module("wechat_macos_ocr")
    run, _, _ = _make_run(tmp_path / "atomic")
    (run / "windows_ocr_checkpoint.json").unlink()
    fake_helper = tmp_path / "fake-vision-helper"
    fake_helper.write_text("synthetic", encoding="utf-8")
    fake_result = {
        "status": "OCR_OK",
        "text": "synthetic OCR",
        "width": 1,
        "height": 1,
        "error": "",
    }
    with patch.object(adapter, "_compile_vision_helper", return_value=fake_helper):
        with patch.object(adapter, "_vision_ocr", return_value=fake_result):
            with patch.object(adapter.os, "replace", wraps=adapter.os.replace) as replace:
                summary = adapter.run("Full", run)

    assert summary["status"] == "OCR_OK"
    assert replace.call_count >= 5
    destinations = [Path(call.args[1]) for call in replace.call_args_list]
    assert all(destination.parent == run for destination in destinations)
    assert not list(run.glob(".*.tmp"))


def test_ocr_rejects_image_bytes_changed_during_ocr(tmp_path: Path) -> None:
    adapter = importlib.import_module("wechat_macos_ocr")
    run, image, _ = _make_run(tmp_path / "race-image")
    (run / "windows_ocr_checkpoint.json").unlink()
    fake_helper = tmp_path / "fake-vision-helper"
    fake_helper.write_text("synthetic", encoding="utf-8")

    def mutate_image(_executable: Path, _image_path: Path) -> dict[str, object]:
        image.write_bytes(b"image-mutated-during-ocr")
        return {"status": "OCR_OK", "text": "stale success", "width": 1, "height": 1, "error": ""}

    with patch.object(adapter, "_compile_vision_helper", return_value=fake_helper):
        with patch.object(adapter, "_vision_ocr", side_effect=mutate_image):
            with pytest.raises(RuntimeError, match="source changed during"):
                adapter.run("Canary", run)
    assert not (run / "windows_ocr_canary.json").exists()


def test_ocr_rejects_slice_bytes_changed_during_ocr(tmp_path: Path) -> None:
    adapter = importlib.import_module("wechat_macos_ocr")
    run, _, _ = _make_run(tmp_path / "race-part", sliced=True)
    (run / "windows_ocr_checkpoint.json").unlink()
    part = run / "ocr_long_slices" / "img_01_part_01.png"
    fake_helper = tmp_path / "fake-vision-helper"
    fake_helper.write_text("synthetic", encoding="utf-8")

    def mutate_part(_executable: Path, _image_path: Path) -> dict[str, object]:
        part.write_bytes(b"part-mutated-during-ocr")
        return {"status": "OCR_OK", "text": "stale success", "width": 1, "height": 1, "error": ""}

    with patch.object(adapter, "_compile_vision_helper", return_value=fake_helper):
        with patch.object(adapter, "_vision_ocr", side_effect=mutate_part):
            with pytest.raises(RuntimeError, match="source changed during"):
                adapter.run("Canary", run)
    assert not (run / "windows_ocr_canary.json").exists()


def test_cache_rejects_image_changed_after_cache_sha_validation(tmp_path: Path) -> None:
    adapter = importlib.import_module("wechat_macos_ocr")
    run, image, _ = _make_run(tmp_path / "cache-race-image")
    original_sha256 = adapter._sha256_file
    calls = 0

    def mutate_after_cache_sha(path: Path) -> str:
        nonlocal calls
        calls += 1
        digest = original_sha256(path)
        if calls == 2:
            image.write_bytes(b"image-mutated-after-cache-validation")
        return digest

    fake_helper = tmp_path / "fake-vision-helper"
    fake_helper.write_text("synthetic", encoding="utf-8")
    fake_result = {
        "status": "OCR_OK",
        "text": "fresh OCR",
        "width": 1,
        "height": 1,
        "error": "",
    }
    with patch.object(adapter, "_sha256_file", side_effect=mutate_after_cache_sha):
        with patch.object(adapter, "_compile_vision_helper", return_value=fake_helper):
            with patch.object(adapter, "_vision_ocr", return_value=fake_result) as vision_ocr:
                with pytest.raises(RuntimeError, match="source changed during"):
                    adapter.run("Full", run)

    assert calls >= 2
    vision_ocr.assert_not_called()
    assert not (run / "windows_ocr_results.json").exists()
    assert not (run / "windows_ocr_results.md").exists()
    assert not (run / "wechat_article_ocr_text.txt").exists()


def test_cache_rejects_slice_changed_after_cache_sha_validation(tmp_path: Path) -> None:
    adapter = importlib.import_module("wechat_macos_ocr")
    run, _, _ = _make_run(tmp_path / "cache-race-slice", sliced=True)
    part = run / "ocr_long_slices" / "img_01_part_01.png"
    original_sha256 = adapter._sha256_file
    calls = 0

    def mutate_after_cache_sha(path: Path) -> str:
        nonlocal calls
        calls += 1
        digest = original_sha256(path)
        if calls == 4:
            part.write_bytes(b"part-mutated-after-cache-validation")
        return digest

    fake_helper = tmp_path / "fake-vision-helper"
    fake_helper.write_text("synthetic", encoding="utf-8")
    fake_result = {
        "status": "OCR_OK",
        "text": "fresh OCR",
        "width": 1,
        "height": 1,
        "error": "",
    }
    with patch.object(adapter, "_sha256_file", side_effect=mutate_after_cache_sha):
        with patch.object(adapter, "_compile_vision_helper", return_value=fake_helper):
            with patch.object(adapter, "_vision_ocr", return_value=fake_result) as vision_ocr:
                with pytest.raises(RuntimeError, match="source changed during"):
                    adapter.run("Full", run)

    assert calls >= 4
    vision_ocr.assert_not_called()
    assert not (run / "windows_ocr_results.json").exists()
    assert not (run / "windows_ocr_results.md").exists()
    assert not (run / "wechat_article_ocr_text.txt").exists()
