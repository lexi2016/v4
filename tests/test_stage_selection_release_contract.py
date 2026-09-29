"""Offline source-closure contracts; no launchd, Mac or market-data acceptance."""
import hashlib
import importlib
from pathlib import Path
import shutil

import pytest

from ops import stage_service_overlay_contract as overlay

ROOT = Path(__file__).resolve().parents[1]
HELPERS = tuple(f"stage_center/_selection_parts/{name}.py" for name in
                ("store_publication", "store_verification", "artifact_codec"))


def contract():
    return importlib.import_module("ops.stage_selection_release_contract")


def test_both_existing_overlay_modes_include_selection_store_helpers():
    assert set(HELPERS) <= set(overlay.STAGE_SERVICE_OVERLAY_PATHS)
    assert set(HELPERS) <= set(overlay.LEGACY_STAGE_SERVICE_OVERLAY_PATHS)


def test_current_reviewed_closure_has_exact_source_hashes_and_all_lazy_helpers():
    c = contract()
    c.require_selection_closure(source_root=ROOT, overlay_paths=tuple(c.STAGE_SELECTION_SHA256))
    assert set(HELPERS) <= set(c.STAGE_SELECTION_SHA256)
    assert c.STAGE_SELECTION_SHA256["domains/research.py"] == hashlib.sha256((ROOT / "domains/research.py").read_bytes()).hexdigest()


@pytest.mark.parametrize("helper", HELPERS)
def test_missing_or_unselected_helper_is_rejected(helper):
    c = contract()
    paths = tuple(p for p in c.STAGE_SELECTION_SHA256 if p != helper)
    with pytest.raises(ValueError, match="incomplete"):
        c.require_selection_closure(source_root=ROOT, overlay_paths=paths)


@pytest.mark.parametrize("mutation", ["missing", "sha", "symlink"])
def test_bad_helper_cannot_enter_release(tmp_path, mutation):
    c = contract()
    for path in c.STAGE_SELECTION_SHA256:
        dest = tmp_path / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, dest)
    path = tmp_path / HELPERS[0]
    if mutation == "missing":
        path.unlink()
    elif mutation == "sha":
        path.write_bytes(path.read_bytes() + b"\n# drift\n")
    else:
        path.unlink()
        path.symlink_to(ROOT / HELPERS[0])
    with pytest.raises((ValueError, OSError)):
        c.require_selection_closure(source_root=tmp_path, overlay_paths=tuple(c.STAGE_SELECTION_SHA256))


def test_overlay_checker_does_not_allow_a_partial_cohort():
    with pytest.raises(ValueError, match="incomplete"):
        overlay.require_stage_overlay_source_hashes(source_root=ROOT,
            overlay_paths=("stage_center/selection.py",))


def test_manifest_compatibility_preserves_identity_conflict_and_missing_rejection(tmp_path):
    app, release = tmp_path / "r" / "app", tmp_path / "r"
    payload = {"schema_version": "v4.stage_service_candidate.v2", "candidate":
               {"app_root": str(app), "root": str(release), "release_id": "synthetic"}}
    actual = overlay._active_stage_manifest_identity(payload, app_root=app, release_root=release)
    assert actual["release_id"] == "synthetic"
    with pytest.raises(ValueError, match="conflict"):
        overlay._active_stage_manifest_identity({**payload, "app_root": "/wrong"}, app_root=app, release_root=release)
    bad = {**payload, "candidate": {"app_root": str(app), "root": str(release)}}
    with pytest.raises(ValueError, match="missing"):
        overlay._active_stage_manifest_identity(bad, app_root=app, release_root=release)


def test_new_lazy_import_needs_explicit_review_even_after_root_repin(tmp_path, monkeypatch):
    c = contract()
    for path in c.STAGE_SELECTION_SHA256:
        dest = tmp_path / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, dest)
    owner = tmp_path / "stage_center/consumer.py"
    owner.write_bytes(owner.read_bytes() + b"\ndef synthetic_future_dependency():\n    from stage_center.not_reviewed import value\n    return value\n")
    (tmp_path / "stage_center/not_reviewed.py").write_text("value = 1\n")
    monkeypatch.setitem(c.STAGE_SELECTION_SHA256, "stage_center/consumer.py",
                        hashlib.sha256(owner.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="unreviewed"):
        c.require_selection_closure(source_root=tmp_path, overlay_paths=tuple(c.STAGE_SELECTION_SHA256))
