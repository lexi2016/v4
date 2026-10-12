from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from infrastructure.research_hourly_store import (
    HourlyResearchStore as SharedHourlyResearchStore,
)
from infrastructure.research_store import HourlyResearchStore
from ops import research_shared_bundle as shared_bundle
from ops import run_hourly_research as hourly_runner


REPO_ROOT = Path(__file__).resolve().parents[1]


def _stage_common_bundle(target_root: Path) -> dict:
    source = shared_bundle.build_research_shared_bundle(root=REPO_ROOT)
    for relative in (source["manifest_path"], *(item["path"] for item in source["modules"])):
        source_path = REPO_ROOT / relative
        target_path = target_root / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target_path)
    return shared_bundle.build_research_shared_bundle(root=target_root)


def test_bundle_records_stable_relative_paths_and_raw_file_shas() -> None:
    bundle = shared_bundle.build_research_shared_bundle(root=REPO_ROOT)
    assert bundle == shared_bundle.build_research_shared_bundle(root=REPO_ROOT)
    assert bundle["schema_version"] == "v4.research_shared_bundle.v1"
    assert bundle["manifest_sha256"]
    assert len(bundle["bundle_sha256"]) == 64

    modules = {entry["path"]: entry["sha256"] for entry in bundle["modules"]}
    assert "infrastructure/research_hourly_store.py" in modules
    assert "infrastructure/_research_store_parts/hourly_sources.py" in modules
    assert "infrastructure/_research_store_parts/hourly_publish.py" in modules
    assert "ops/research_shared_bundle.py" in modules
    assert "infrastructure/trading_safety.py" in modules
    assert all(
        hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest() == digest
        for relative, digest in modules.items()
    )


def test_api_and_scheduler_candidates_stage_identical_common_bytes(
    tmp_path: Path,
) -> None:
    api_bundle = _stage_common_bundle(tmp_path / "api")
    scheduler_bundle = _stage_common_bundle(tmp_path / "scheduler")

    assert api_bundle == scheduler_bundle
    assert api_bundle["bundle_sha256"] == shared_bundle.build_research_shared_bundle(
        root=REPO_ROOT
    )["bundle_sha256"]


def test_transformer_identity_binds_bundle_and_runtime_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = hourly_runner._research_transformer_identity_manifest()
    expected_components = {
        "contracts.research",
        "domains.research",
        "domains.research_hourly",
        "infrastructure.data_store",
        "infrastructure.owned_path",
        "infrastructure.owned_io",
        "infrastructure.interprocess_lock",
        "infrastructure.market_time",
        "infrastructure.trading_safety",
        "infrastructure.research_store",
        "ops.collect_hourly_research_input",
        "ops.run_hourly_research",
    }
    assert expected_components.issubset(identity["components"])
    assert identity["shared_bundle_sha256"] == shared_bundle.build_research_shared_bundle()[
        "bundle_sha256"
    ]

    original_bundle = shared_bundle.build_research_shared_bundle()
    monkeypatch.setattr(
        shared_bundle,
        "build_research_shared_bundle",
        lambda: {**original_bundle, "bundle_sha256": "a" * 64},
    )
    changed_identity = hourly_runner._research_transformer_identity_manifest()
    assert changed_identity["shared_bundle_sha256"] != identity["shared_bundle_sha256"]
    assert changed_identity != identity


def test_bundle_rejects_traversal_and_duplicate_module_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "candidate"
    (root / "deployment").mkdir(parents=True)
    manifest_path = root / shared_bundle.DEFAULT_MANIFEST_PATH
    traversal = {
        "schema_version": shared_bundle.MANIFEST_SCHEMA_VERSION,
        "bundle_id": "test",
        "module_paths": ["../outside.py"],
    }
    manifest_path.write_text(json.dumps(traversal), encoding="utf-8")
    with pytest.raises(ValueError, match="module path"):
        shared_bundle.build_research_shared_bundle(root=root)

    duplicate = {
        **traversal,
        "module_paths": ["ops/research_shared_bundle.py"] * 2,
    }
    manifest_path.write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        shared_bundle.build_research_shared_bundle(root=root)


def test_store_facade_keeps_shared_entrypoints() -> None:
    assert issubclass(HourlyResearchStore, SharedHourlyResearchStore)
    for name in (
        "publish",
        "list_slots",
        "read_exact",
        "read_latest_for_date",
        "reuse_matching_source",
        "read_latest",
        "_normalize_ready_empty_owned_path",
        "_validate_ready_empty_source",
    ):
        assert hasattr(HourlyResearchStore, name)
