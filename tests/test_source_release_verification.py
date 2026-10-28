from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "ops" / "verify_source_release.py"
SPEC = importlib.util.spec_from_file_location("verify_source_release", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _file(path: str, digest: str, mode: int = 0o644) -> object:
    return MODULE.FileEntry(path, "file", digest, mode)


def _link(path: str, target: str, exists: bool = True) -> object:
    return MODULE.FileEntry(path, "symlink", None, None, target, exists)


def test_equal_files_and_upstream_links_pass_selected_scope() -> None:
    source_files = {"stage_center/runner.py": _file("stage_center/runner.py", "abc")}
    release_files = {"stage_center/runner.py": _file("stage_center/runner.py", "abc")}
    source_links = {"upstreams/review_core": _link("upstreams/review_core", "/release/review_core")}
    release_links = {"upstreams/review_core": _link("upstreams/review_core", "/release/review_core")}

    result = MODULE.compare_entry_sets(source_files, release_files, source_links, release_links)

    assert result["status"] == "PASS"
    assert result["same_origin_selected_scope"] is True
    assert result["missing_files_in_release"] == []
    assert result["mismatched_links"] == []


def test_changed_mode_missing_file_and_extra_file_are_reported() -> None:
    source_files = {
        "stage_center/runner.py": _file("stage_center/runner.py", "abc", 0o644),
        "stage_center/consumer.py": _file("stage_center/consumer.py", "def"),
    }
    release_files = {
        "stage_center/runner.py": _file("stage_center/runner.py", "abc", 0o755),
        "stage_center/extra.py": _file("stage_center/extra.py", "xyz"),
    }

    result = MODULE.compare_entry_sets(source_files, release_files, {}, {})

    assert result["status"] == "FAIL"
    assert result["missing_files_in_release"] == ["stage_center/consumer.py"]
    assert result["extra_files_in_release"] == ["stage_center/extra.py"]
    assert [item["path"] for item in result["mismatched_files"]] == [
        "stage_center/runner.py"
    ]


def test_symlink_comparison_records_identity_without_reading_target(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    release_root = tmp_path / "release"
    source_root.mkdir()
    release_root.mkdir()
    (source_root / "upstreams").mkdir()
    (release_root / "upstreams").mkdir()
    source_target = tmp_path / "source-target"
    release_target = tmp_path / "release-target"
    source_target.mkdir()
    release_target.mkdir()
    (source_root / "upstreams" / "review_core").symlink_to(source_target, target_is_directory=True)
    (release_root / "upstreams" / "review_core").symlink_to(release_target, target_is_directory=True)

    source_links = MODULE.collect_link_entries(source_root, ("upstreams/review_core",))
    release_links = MODULE.collect_link_entries(release_root, ("upstreams/review_core",))

    assert source_links["upstreams/review_core"].kind == "symlink"
    assert source_links["upstreams/review_core"].target == str(source_target)
    assert release_links["upstreams/review_core"].target == str(release_target)
    assert source_links["upstreams/review_core"].target_exists is True
    assert release_links["upstreams/review_core"].target_exists is True


def test_broken_required_link_cannot_pass_selected_scope() -> None:
    source_links = {"upstreams/review_core": _link("upstreams/review_core", "/missing", False)}
    release_links = {"upstreams/review_core": _link("upstreams/review_core", "/missing", False)}

    result = MODULE.compare_entry_sets({}, {}, source_links, release_links)

    assert result["status"] == "FAIL"
    assert result["source_links_with_missing_targets"] == ["upstreams/review_core"]
    assert result["release_links_with_missing_targets"] == ["upstreams/review_core"]


def test_compare_roots_rejects_same_resolved_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "stage_center").mkdir()
    (source / "stage_center" / "runner.py").write_text("pass\n")
    alias = tmp_path / "release-alias"
    alias.symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError, match="distinct"):
        MODULE.compare_roots(
            source,
            alias,
            file_roots=("stage_center",),
            link_paths=(),
            excludes=(),
        )


def _git_fixture(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    release = tmp_path / "release"
    (source / "stage_center").mkdir(parents=True)
    (release / "stage_center").mkdir(parents=True)
    (source / "upstreams").mkdir()
    (release / "upstreams").mkdir()
    (source / "v3_shared_data").mkdir()
    (release / "v3_shared_data").mkdir()
    common_target = tmp_path / "shared-target"
    common_target.mkdir()
    (source / "upstreams" / "review_core").symlink_to(common_target, target_is_directory=True)
    (release / "upstreams" / "review_core").symlink_to(common_target, target_is_directory=True)
    (source / "upstreams" / "v3.5").symlink_to(common_target, target_is_directory=True)
    (release / "upstreams" / "v3.5").symlink_to(common_target, target_is_directory=True)
    (source / "v3_shared_data").rmdir()
    (release / "v3_shared_data").rmdir()
    (source / "v3_shared_data").symlink_to(common_target, target_is_directory=True)
    (release / "v3_shared_data").symlink_to(common_target, target_is_directory=True)
    (source / "stage_center" / "runner.py").write_text("pass\n")
    (release / "stage_center" / "runner.py").write_text("pass\n")
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "source-test"], cwd=source, check=True)
    subprocess.run(["git", "add", "stage_center/runner.py"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=source, check=True)
    return source, release


def test_build_receipt_marks_custom_scope_and_main_writes_receipt(tmp_path: Path) -> None:
    source, release = _git_fixture(tmp_path)
    receipt_path = tmp_path / "evidence" / "receipt.json"
    code = MODULE.main(
        [
            "--source-root",
            str(source),
            "--release-root",
            str(release),
            "--receipt",
            str(receipt_path),
            "--file-root",
            "stage_center",
            "--link-path",
            "upstreams/review_core",
            "--link-path",
            "upstreams/v3.5",
            "--link-path",
            "v3_shared_data",
        ]
    )
    assert code == 0
    payload = json.loads(receipt_path.read_text())
    assert payload["comparison"]["status"] == "PASS"
    assert payload["scope"]["scope_mode"] == "CUSTOM_SCOPE"
    assert payload["scope"]["fixed_acceptance_scope"] is False
    assert payload["selected_scope_status"] == "CUSTOM_SCOPE"
    assert payload["fixed_scope_status"] == "NOT_APPLICABLE"


def test_build_receipt_rejects_scope_mode_that_does_not_match_actual_scope(tmp_path: Path) -> None:
    source, release = _git_fixture(tmp_path)
    with pytest.raises(ValueError, match="does not match"):
        MODULE.build_receipt(
            source,
            release,
            file_roots=("stage_center",),
            link_paths=(),
            excludes=(),
            scope_mode="FIXED_CANONICAL",
        )
