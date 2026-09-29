from __future__ import annotations

import json
import hashlib
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ops import build_release_candidate as builder
from ops import build_release_candidate_stage as stage_builder


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FROZEN_STAGE_SOURCE = REPOSITORY_ROOT / "tests" / "fixtures" / "stage_overlay"

STRICT_COHORT = (
    "ops/run_stage_center_nodes.py",
    "ops/run_stage_center_worker.py",
    "stage_center/runner.py",
    "stage_center/commit_store.py",
    "stage_center/consumer.py",
    "ops/run_stage_center_tick.py",
    "domains/preselection.py",
    "domains/task_status.py",
    "stage_center_tick_config.json",
)
LEGACY_STAGE_OVERLAYS = (
    "infrastructure/preselection_pool_store.py",
    "ops/recover_selection_observations.py",
    "ops/run_stage_center_nodes.py",
    "stage_center/end_to_end_deadline.py",
    "stage_center/formula_margin_shadow.py",
    "stage_center/live_collectors.py",
    "stage_center/selection.py",
    "stage_center/hk_stage8/__init__.py",
    "stage_center/hk_stage8/builders.py",
    "stage_center/hk_stage8/precapture.py",
    "stage_center/hk_stage8/rtdata.py",
    "stage_center/hk_stage8/snapshot.py",
    "stage_center/input_contracts.py",
    "stage_center/runner.py",
    "stage_center_tick_config.json",
)
NEW_STAGE_OVERLAYS = (
    "ops/run_stage_center_worker.py",
    "stage_center/commit_store.py",
    "stage_center/consumer.py",
    "ops/run_stage_center_tick.py",
    "domains/preselection.py",
    "domains/task_status.py",
)
STRICT_COHORT_SHA256 = {
    "ops/run_stage_center_nodes.py": "af3de347834b1c9672d4752944d8aec7c641f23d1e3294a723e42add7bd0592d",
    "ops/run_stage_center_worker.py": "1725efca47cac8b05431ec89b25ce9bb296606d8701ee0d533f42f3de0e87fbb",
    "stage_center/runner.py": "648fe7af52df1b4eba31802361f9af2d03decbbebb3286ecc7a5dc0b06523205",
    "stage_center/commit_store.py": "607b29428f6c6f8a9dea6ac43a54c4aacaaa737e842616f61d8baccf727628f7",
    "stage_center/consumer.py": "9e3a864c74eaec6c616b911b09c167c8cb407db8435343c1b522de4f4c9459eb",
    "ops/run_stage_center_tick.py": "c28037a9b1c8fdd078daab0e5446065188beda6544ddc8ade6208bb0a7a40394",
    "domains/preselection.py": "5f26e01e23d285a1e2a4b33c46a16943f77d74656f7482832289e7b83838eefd",
    "domains/task_status.py": "047cfb2b6a8c165857b2841f137a86c9587a1a6e81199efdf71d508d05589300",
    "stage_center_tick_config.json": "b59d96204a7ff8e0056dcab9dc406493cfd36695f630c9c77f056b5eb7b2652c",
}
NEW_RELEASE_CLOSURE_PINS = {
    "stage_center/_live_collectors_parts/selection_builder_registry.py": "5b315c482723f4bbfb187e36241ea422f2a59518a2056be037d1fdbe2f00eb22",
    "stage_center/_selection_parts/a_live.py": "b7faa3286df4f0312075c7a4563d3f4deed463d3f10ab2c4902967e8d5d7781d",
    "stage_center/_selection_parts/market_quality.py": "726cd4987a070bf78ac7416756f3cbba86633b1176f6f43535ac747263474b3f",
    "stage_center/_selection_parts/primitives_io.py": "6f492e2d32fab11970993adfe694cf159cccafe2205b288685917f93560e2501",
    "stage_center/_selection_parts/selection_envelope.py": "be7748ff72fd85375fc6575a6a40281fb1518c8faf0e55f352f167fbbc42bd89",
    "stage_center/_raw_store_parts/__init__.py": "29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8",
    "stage_center/_raw_store_parts/_namespace.py": "45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1",
    "stage_center/_raw_store_parts/codec.py": "504b97a64f483db17026dbeed6d5084fbc18ee972be60ad9e069ebd038708572",
    "stage_center/_raw_store_parts/filesystem_io.py": "f904f4086d4debfc32f5ad33ec2717cda522a59f2e15a3518c7aa83b91eef2b1",
    "stage_center/_raw_store_parts/receipt_identity.py": "b33c496a6052b450959a9b886c79ad8d5686230e320dbc99bfd98a3e8265a8f0",
    "stage_center/_raw_store_parts/transaction_publish.py": "4c28d92667428cfeced54e074e800337ca88b7e87d8a5468a9464b668ca9b24e",
    "stage_center/_raw_store_parts/transaction_read.py": "8b7e88dc5e5f41456e5222f1a5c08c5dcd05f5e5d7f2c179fd26652bff2932b6",
    "stage_center/_selection_parts/artifact_codec.py": "6c0ddaed1dfe7a066be9aeb1c726e2357f5c1814b0baca834c37bb1879aeeb9d",
    "stage_center/_selection_parts/store_publication.py": "e3ee42413c35aa098cddc136795fcf04a37898bc2224d815cbe9e2b854c5c968",
    "stage_center/_selection_parts/store_verification.py": "af061784202e35bd7c497208407ce1313876683544d89bcb05153ebca1e7af0f",
}


def _write_synthetic_active_release(
    tmp_path: Path,
    config: dict,
    *,
    active_publication_mode: str | None = None,
    service_label: str = builder.STAGE_SERVICE_LABEL,
    deadline_only: bool = False,
    selection_runtime_baseline: bool = False,
) -> tuple[Path, Path]:
    release_root = tmp_path / "formal" / "releases" / "active-r4-fixture"
    app_root = release_root / "app"
    (app_root / "ops").mkdir(parents=True)
    (app_root / "upstreams" / "v3_shared_data").mkdir(parents=True)
    (app_root / "manager").mkdir()
    (app_root / "ops" / "run_stage_center_nodes.py").write_text("# active entry\n")
    (app_root / "upstreams" / "v3_shared_data" / "README.txt").write_text("fixture shared package\n")
    (app_root / "manager" / "state-reference.json").write_text('{"root":"fixture-manager-root"}\n')
    if selection_runtime_baseline:
        for module in ("stage_center", "infrastructure"):
            shutil.copytree(REPOSITORY_ROOT / module, app_root / module, dirs_exist_ok=True)
        for relative in (
            "stage_center/_selection_parts/artifact_codec.py",
            "stage_center/_selection_parts/store_publication.py",
            "stage_center/_selection_parts/store_verification.py",
        ):
            (app_root / relative).unlink()
    active_config = dict(config)
    active_config.update({
        "release_id": "active-r4-fixture",
        "shared_data_root": str(app_root / "upstreams" / "v3_shared_data"),
    })
    if active_publication_mode is not None:
        active_config["publication_mode"] = active_publication_mode
    (app_root / "stage_center_tick_config.json").write_text(
        json.dumps(active_config, ensure_ascii=False, indent=2) + "\n"
    )
    inventory = builder.inventory_tree(app_root)
    manifest = {
        "schema_version": "fixture.active.release.v1",
        "release_id": "active-r4-fixture",
        "release_root": str(release_root),
        "app_root": str(app_root),
        "application_inventory": {
            "aggregate_sha256": builder.inventory_digest(inventory),
            "entries": inventory,
        },
    }
    release_root.mkdir(parents=True, exist_ok=True)
    (release_root / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    plist_path = tmp_path / "launchagents" / "stage.plist"
    plist_path.parent.mkdir(parents=True)
    arguments = [
            sys.executable,
            "-B",
            str(app_root / "ops" / "run_stage_center_nodes.py"),
            "--config",
            str(app_root / "stage_center_tick_config.json"),
    ]
    if deadline_only:
        arguments.append("--deadline-only")
    plist_path.write_bytes(plistlib.dumps({
        "Label": service_label,
        "ProgramArguments": arguments,
        "WorkingDirectory": str(app_root),
        "EnvironmentVariables": {
            "NODE_CALENDAR_WAIT_MAX_SECONDS": "5",
            "NODE_MAX_ATTEMPTS": "3",
            "NODE_RETRY_BACKOFF_SECONDS": "60",
            "PRODUCTION_ALLOWED": "false",
            "BUY_GATE_UPDATED": "false",
            "ORDERS_SENT": "false",
            "V4_MANAGER_RESEARCH_STATE_ROOT": str(tmp_path / "manager-state"),
        },
    }))
    return release_root, plist_path


def _copy_strict_source(tmp_path: Path, *, strict: bool) -> tuple[Path, dict]:
    source_root = tmp_path / "source"
    for relative in stage_builder.STAGE_SERVICE_OVERLAY_PATHS:
        destination = source_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if relative in stage_builder.STAGE_SERVICE_RELEASE_CLOSURE_SHA256:
            source = REPOSITORY_ROOT / relative
            assert hashlib.sha256(source.read_bytes()).hexdigest() == (
                stage_builder.STAGE_SERVICE_RELEASE_CLOSURE_SHA256[relative]
            )
            shutil.copy2(source, destination)
            continue
        source = FROZEN_STAGE_SOURCE / relative
        if relative in STRICT_COHORT_SHA256:
            assert hashlib.sha256(source.read_bytes()).hexdigest() == STRICT_COHORT_SHA256[relative]
            shutil.copy2(source, destination)
        else:
            destination.write_text(f"# preexisting allowlisted fixture: {relative}\n")
    (source_root / "apps" / "web" / "unlisted-source-file.txt").parent.mkdir(parents=True)
    (source_root / "apps" / "web" / "unlisted-source-file.txt").write_text("must not enter package\n")
    config_path = source_root / "stage_center_tick_config.json"
    config = json.loads(config_path.read_text())
    if not strict:
        config.pop("publication_mode", None)
        config["publication_mode"] = "legacy_partial_overlay"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    return source_root, config


def _copy_original_legacy_source(tmp_path: Path) -> tuple[Path, dict]:
    source_root = tmp_path / "legacy-source"
    for relative in LEGACY_STAGE_OVERLAYS:
        destination = source_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if relative in stage_builder.STAGE_SERVICE_RELEASE_CLOSURE_SHA256:
            source = REPOSITORY_ROOT / relative
            assert hashlib.sha256(source.read_bytes()).hexdigest() == (
                stage_builder.STAGE_SERVICE_RELEASE_CLOSURE_SHA256[relative]
            )
            shutil.copy2(source, destination)
            continue
        source = FROZEN_STAGE_SOURCE / relative
        if relative in STRICT_COHORT_SHA256:
            assert hashlib.sha256(source.read_bytes()).hexdigest() == STRICT_COHORT_SHA256[relative]
            shutil.copy2(source, destination)
        else:
            destination.write_text(f"# original legacy allowlisted fixture: {relative}\n")
    for relative in stage_builder.STAGE_SERVICE_RELEASE_CLOSURE_PATHS:
        if relative not in stage_builder.LEGACY_STAGE_SERVICE_OVERLAY_PATHS:
            continue
        destination = source_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = REPOSITORY_ROOT / relative
        assert hashlib.sha256(source.read_bytes()).hexdigest() == (
            stage_builder.STAGE_SERVICE_RELEASE_CLOSURE_SHA256[relative]
        )
        shutil.copy2(source, destination)
    config_path = source_root / "stage_center_tick_config.json"
    config = json.loads(config_path.read_text())
    config.pop("publication_mode", None)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    return source_root, config


def _patch_offline_builder(monkeypatch) -> None:
    monkeypatch.setattr(builder, "_run_git", lambda *_args, **_kwargs: "fixture-source-commit")
    monkeypatch.setattr(
        stage_builder,
        "_probe_stage_runtime",
        lambda python: {"status": "OBSERVED_RESOLVED", "python": str(python), "fixture": True},
    )


def _build_partial_candidate(
    *,
    source_root: Path,
    baseline_release: Path,
    stage_plist: Path,
    candidate_root: Path,
    receipt_path: Path,
    include_config: bool,
) -> dict[str, object]:
    overlays = ["ops/run_stage_center_nodes.py", "stage_center/runner.py"]
    if include_config:
        overlays.append("stage_center_tick_config.json")
    return builder.build_stage_service_candidate(
        source_root=source_root,
        candidate_root=candidate_root,
        stage_plist_path=stage_plist,
        runtime_python=Path(sys.executable),
        release_id="effective-config-fixture",
        formal_release_root=candidate_root.parent.parent / "formal",
        receipt_path=receipt_path,
        baseline_release_root=baseline_release,
        overlay_paths=tuple(overlays),
    )


def test_strict_cluster_rejects_incomplete_source_overlay_before_package_build(tmp_path, monkeypatch):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_strict_source(tmp_path, strict=True)
    baseline_release, stage_plist = _write_synthetic_active_release(tmp_path, source_config)
    candidate_root = tmp_path / "candidates" / "incomplete-strict-stage"
    receipt_path = tmp_path / "evidence" / "incomplete-receipt.json"

    with pytest.raises(ValueError, match="strict Stage overlay requires the complete reviewed cohort"):
        builder.build_stage_service_candidate(
            source_root=source_root,
            candidate_root=candidate_root,
            stage_plist_path=stage_plist,
            runtime_python=Path(sys.executable),
            release_id="strict-stage-fixture",
            formal_release_root=tmp_path / "formal",
            receipt_path=receipt_path,
            baseline_release_root=baseline_release,
            overlay_paths=(
                "ops/run_stage_center_nodes.py",
                "stage_center/runner.py",
                "stage_center_tick_config.json",
            ),
        )

    assert not candidate_root.exists()
    assert not receipt_path.exists()


def test_strict_cluster_rejects_missing_source_member_before_package_build(tmp_path, monkeypatch):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_strict_source(tmp_path, strict=True)
    baseline_release, stage_plist = _write_synthetic_active_release(tmp_path, source_config)
    missing_path = source_root / "stage_center" / "consumer.py"
    missing_path.unlink()
    candidate_root = tmp_path / "candidates" / "missing-member-strict-stage"

    with pytest.raises(FileNotFoundError, match="strict Stage overlay source cohort is incomplete"):
        builder.build_stage_service_candidate(
            source_root=source_root,
            candidate_root=candidate_root,
            stage_plist_path=stage_plist,
            runtime_python=Path(sys.executable),
            release_id="strict-stage-fixture",
            formal_release_root=tmp_path / "formal",
            receipt_path=tmp_path / "evidence" / "missing-member-receipt.json",
            baseline_release_root=baseline_release,
            overlay_paths=STRICT_COHORT,
        )

    assert not candidate_root.exists()


@pytest.mark.parametrize(
    "missing_relative",
    ("ops/run_stage_center_worker.py", "stage_center/commit_store.py"),
)
def test_strict_default_rejects_missing_expanded_source_before_package_build(
    tmp_path, monkeypatch, missing_relative,
):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_strict_source(tmp_path, strict=True)
    baseline_release, stage_plist = _write_synthetic_active_release(tmp_path, source_config)
    (source_root / missing_relative).unlink()
    candidate_root = tmp_path / "candidates" / f"missing-expanded-{Path(missing_relative).name}"
    receipt_path = tmp_path / "evidence" / f"missing-expanded-{Path(missing_relative).name}.json"

    with pytest.raises(FileNotFoundError, match="strict Stage overlay source cohort is incomplete"):
        builder.build_stage_service_candidate(
            source_root=source_root,
            candidate_root=candidate_root,
            stage_plist_path=stage_plist,
            runtime_python=Path(sys.executable),
            release_id="strict-default-fixture",
            formal_release_root=tmp_path / "formal",
            receipt_path=receipt_path,
            baseline_release_root=baseline_release,
        )

    assert not candidate_root.exists()
    assert not receipt_path.exists()


def test_active_strict_config_rejects_partial_overlay_without_config_selection(tmp_path, monkeypatch):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_strict_source(tmp_path, strict=False)
    baseline_release, stage_plist = _write_synthetic_active_release(
        tmp_path,
        source_config,
        active_publication_mode="strict_commit_required",
    )
    candidate_root = tmp_path / "candidates" / "active-strict-incomplete-stage"
    receipt_path = tmp_path / "evidence" / "active-strict-incomplete-receipt.json"

    with pytest.raises(ValueError, match="strict Stage overlay requires the complete reviewed cohort"):
        builder.build_stage_service_candidate(
            source_root=source_root,
            candidate_root=candidate_root,
            stage_plist_path=stage_plist,
            runtime_python=Path(sys.executable),
            release_id="strict-stage-fixture",
            formal_release_root=tmp_path / "formal",
            receipt_path=receipt_path,
            baseline_release_root=baseline_release,
            overlay_paths=("ops/run_stage_center_nodes.py", "stage_center/runner.py"),
        )

    assert not candidate_root.exists()
    assert not receipt_path.exists()


def test_nonselected_config_uses_active_legacy_mode_when_source_is_strict(tmp_path, monkeypatch):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_strict_source(tmp_path, strict=True)
    baseline_release, stage_plist = _write_synthetic_active_release(
        tmp_path,
        source_config,
        active_publication_mode="legacy_partial_overlay",
    )
    candidate_root = tmp_path / "candidates" / "active-legacy-nonselected-config"
    receipt_path = tmp_path / "evidence" / "active-legacy-nonselected-config.json"

    _build_partial_candidate(
        source_root=source_root,
        baseline_release=baseline_release,
        stage_plist=stage_plist,
        candidate_root=candidate_root,
        receipt_path=receipt_path,
        include_config=False,
    )

    config = json.loads((candidate_root / "app" / "stage_center_tick_config.json").read_text())
    assert config["publication_mode"] == "legacy_partial_overlay"


def test_selected_strict_source_config_rejects_partial_overlay_with_active_legacy(tmp_path, monkeypatch):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_strict_source(tmp_path, strict=True)
    baseline_release, stage_plist = _write_synthetic_active_release(
        tmp_path,
        source_config,
        active_publication_mode="legacy_partial_overlay",
    )
    candidate_root = tmp_path / "candidates" / "source-strict-selected-config"
    receipt_path = tmp_path / "evidence" / "source-strict-selected-config.json"

    with pytest.raises(ValueError, match="strict Stage overlay requires the complete reviewed cohort"):
        _build_partial_candidate(
            source_root=source_root,
            baseline_release=baseline_release,
            stage_plist=stage_plist,
            candidate_root=candidate_root,
            receipt_path=receipt_path,
            include_config=True,
        )

    assert not candidate_root.exists()
    assert not receipt_path.exists()


def test_selected_legacy_source_config_overrides_active_strict_mode(tmp_path, monkeypatch):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_strict_source(tmp_path, strict=False)
    baseline_release, stage_plist = _write_synthetic_active_release(
        tmp_path,
        source_config,
        active_publication_mode="strict_commit_required",
    )
    candidate_root = tmp_path / "candidates" / "source-legacy-selected-config"
    receipt_path = tmp_path / "evidence" / "source-legacy-selected-config.json"

    _build_partial_candidate(
        source_root=source_root,
        baseline_release=baseline_release,
        stage_plist=stage_plist,
        candidate_root=candidate_root,
        receipt_path=receipt_path,
        include_config=True,
    )

    config = json.loads((candidate_root / "app" / "stage_center_tick_config.json").read_text())
    assert config["publication_mode"] == "legacy_partial_overlay"


def test_missing_nonselected_source_config_uses_active_legacy_mode(tmp_path, monkeypatch):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_strict_source(tmp_path, strict=True)
    (source_root / "stage_center_tick_config.json").unlink()
    baseline_release, stage_plist = _write_synthetic_active_release(
        tmp_path,
        source_config,
        active_publication_mode="legacy_partial_overlay",
    )
    candidate_root = tmp_path / "candidates" / "missing-nonselected-source-config"
    receipt_path = tmp_path / "evidence" / "missing-nonselected-source-config.json"

    _build_partial_candidate(
        source_root=source_root,
        baseline_release=baseline_release,
        stage_plist=stage_plist,
        candidate_root=candidate_root,
        receipt_path=receipt_path,
        include_config=False,
    )

    config = json.loads((candidate_root / "app" / "stage_center_tick_config.json").read_text())
    assert config["publication_mode"] == "legacy_partial_overlay"


def test_missing_selected_source_config_fails_before_candidate_creation(tmp_path, monkeypatch):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_strict_source(tmp_path, strict=True)
    (source_root / "stage_center_tick_config.json").unlink()
    baseline_release, stage_plist = _write_synthetic_active_release(
        tmp_path,
        source_config,
        active_publication_mode="legacy_partial_overlay",
    )
    candidate_root = tmp_path / "candidates" / "missing-selected-source-config"
    receipt_path = tmp_path / "evidence" / "missing-selected-source-config.json"

    with pytest.raises(FileNotFoundError, match="Stage overlay source must be a regular file"):
        _build_partial_candidate(
            source_root=source_root,
            baseline_release=baseline_release,
            stage_plist=stage_plist,
            candidate_root=candidate_root,
            receipt_path=receipt_path,
            include_config=True,
        )

    assert not candidate_root.exists()
    assert not receipt_path.exists()


def test_missing_nonselected_source_config_does_not_hide_active_strict_mode(tmp_path, monkeypatch):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_strict_source(tmp_path, strict=False)
    (source_root / "stage_center_tick_config.json").unlink()
    baseline_release, stage_plist = _write_synthetic_active_release(
        tmp_path,
        source_config,
        active_publication_mode="strict_commit_required",
    )
    candidate_root = tmp_path / "candidates" / "missing-nonselected-active-strict"
    receipt_path = tmp_path / "evidence" / "missing-nonselected-active-strict.json"

    with pytest.raises(ValueError, match="strict Stage overlay requires the complete reviewed cohort"):
        _build_partial_candidate(
            source_root=source_root,
            baseline_release=baseline_release,
            stage_plist=stage_plist,
            candidate_root=candidate_root,
            receipt_path=receipt_path,
            include_config=False,
        )

    assert not candidate_root.exists()
    assert not receipt_path.exists()


def test_complete_strict_cohort_is_packaged_with_exact_source_identity(tmp_path, monkeypatch):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_strict_source(tmp_path, strict=True)
    baseline_release, stage_plist = _write_synthetic_active_release(tmp_path, source_config)
    candidate_root = tmp_path / "candidates" / "complete-strict-stage"
    receipt = builder.build_stage_service_candidate(
        source_root=source_root,
        candidate_root=candidate_root,
        stage_plist_path=stage_plist,
        runtime_python=Path(sys.executable),
        release_id="strict-stage-fixture",
        formal_release_root=tmp_path / "formal",
        receipt_path=tmp_path / "evidence" / "complete-receipt.json",
        baseline_release_root=baseline_release,
    )

    assert set(STRICT_COHORT) == set(stage_builder.STRICT_STAGE_SERVICE_OVERLAY_PATHS)
    expected_legacy = tuple(dict.fromkeys((
        *LEGACY_STAGE_OVERLAYS,
        *stage_builder.STAGE_SERVICE_RELEASE_CLOSURE_ADDED_PATHS,
    )))
    expected_full = tuple(dict.fromkeys((
        *LEGACY_STAGE_OVERLAYS,
        *NEW_STAGE_OVERLAYS,
        *stage_builder.STAGE_SERVICE_RELEASE_CLOSURE_ADDED_PATHS,
    )))
    assert stage_builder.LEGACY_STAGE_SERVICE_OVERLAY_PATHS == expected_legacy
    assert set(STRICT_COHORT).issubset(set(stage_builder.STAGE_SERVICE_OVERLAY_PATHS))
    assert stage_builder.STAGE_SERVICE_OVERLAY_PATHS == expected_full
    assert len(stage_builder.STAGE_SERVICE_RELEASE_CLOSURE_SHA256) == 65
    assert len(stage_builder.STAGE_SERVICE_RELEASE_CLOSURE_ADDED_PATHS) == 63
    assert set(NEW_RELEASE_CLOSURE_PINS).issubset(stage_builder.STAGE_SERVICE_RELEASE_CLOSURE_SHA256)
    assert {
        path: stage_builder.STAGE_SERVICE_RELEASE_CLOSURE_SHA256[path]
        for path in NEW_RELEASE_CLOSURE_PINS
    } == NEW_RELEASE_CLOSURE_PINS
    assert set(stage_builder.STAGE_SERVICE_RELEASE_CLOSURE_ADDED_PATHS).issubset(
        set(stage_builder.LEGACY_STAGE_SERVICE_OVERLAY_PATHS)
    )
    assert "domains/task_status.py" not in stage_builder.LEGACY_STAGE_SERVICE_OVERLAY_PATHS
    assert builder.STAGE_SERVICE_OVERLAY_PATHS == stage_builder.STAGE_SERVICE_OVERLAY_PATHS
    assert receipt["stage_overlay_paths"] == list(stage_builder.STAGE_SERVICE_OVERLAY_PATHS)
    manifest = json.loads((candidate_root / "release-manifest.json").read_text())
    entries = manifest["source"]["stage_overlay"]["entries"]
    assert [entry["path"] for entry in entries] == list(stage_builder.STAGE_SERVICE_OVERLAY_PATHS)
    for relative in STRICT_COHORT:
        assert next(entry for entry in entries if entry["path"] == relative)["source_workspace_sha256"] == (
            STRICT_COHORT_SHA256[relative]
        )
        if relative != "stage_center_tick_config.json":
            assert hashlib.sha256((candidate_root / "app" / relative).read_bytes()).hexdigest() == (
                STRICT_COHORT_SHA256[relative]
            )

    candidate_app = candidate_root / "app"
    assert not (candidate_app / "apps" / "web" / "unlisted-source-file.txt").exists()
    assert (candidate_app / "manager" / "state-reference.json").read_text() == (
        '{"root":"fixture-manager-root"}\n'
    )
    config = json.loads((candidate_app / "stage_center_tick_config.json").read_text())
    assert config["publication_mode"] == "strict_commit_required"
    for key in stage_builder.STAGE_DATA_PATH_KEYS:
        if key in source_config:
            assert config[key] == source_config[key]
    assert config["safety"] == {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    assert manifest["source"]["stage_overlay"]["non_overlay_active_release_bytes_preserved"] is True
    staged_plist_path = Path(receipt["service_binding"]["path"])
    staged_plist = plistlib.loads(staged_plist_path.read_bytes())
    assert staged_plist["EnvironmentVariables"]["V4_MANAGER_RESEARCH_STATE_ROOT"] == str(
        tmp_path / "manager-state"
    )
    for key in ("PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT"):
        assert staged_plist["EnvironmentVariables"][key] == "false"
    assert receipt["activation_status"] == "NOT_ACTIVATED"


def test_strict_package_closure_includes_all_pins_and_selection_store_roundtrips(
    tmp_path, monkeypatch,
):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_strict_source(tmp_path, strict=True)
    for module in ("stage_center", "infrastructure"):
        shutil.copytree(REPOSITORY_ROOT / module, source_root / module, dirs_exist_ok=True)
    baseline_release, stage_plist = _write_synthetic_active_release(
        tmp_path, source_config, selection_runtime_baseline=True,
    )
    candidate_root = tmp_path / "candidates" / "strict-selection-roundtrip"
    receipt = builder.build_stage_service_candidate(
        source_root=source_root,
        candidate_root=candidate_root,
        stage_plist_path=stage_plist,
        runtime_python=Path(sys.executable),
        release_id="strict-selection-roundtrip",
        formal_release_root=tmp_path / "formal",
        receipt_path=tmp_path / "evidence" / "strict-selection-roundtrip.json",
        baseline_release_root=baseline_release,
    )

    manifest = json.loads((candidate_root / "release-manifest.json").read_text())
    entries = manifest["source"]["stage_overlay"]["entries"]
    packaged_paths = {entry["path"] for entry in entries}
    assert set(stage_builder.STAGE_SERVICE_RELEASE_CLOSURE_PATHS).issubset(packaged_paths)
    for relative, expected_sha in NEW_RELEASE_CLOSURE_PINS.items():
        packaged = candidate_root / "app" / relative
        assert hashlib.sha256(packaged.read_bytes()).hexdigest() == expected_sha

    candidate_app = candidate_root / "app"
    store_root = tmp_path / "packaged-selection-store"
    script = r'''
import json
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from stage_center.selection import SelectionError, SelectionStore, publish_selection, select_a_stage

store_root = Path(sys.argv[2])
envelope = select_a_stage(
    [{"code": "A.000001", "first_open": 10.0, "last_close": 10.2,
      "high": 10.4, "low": 9.9, "amount": 1000000,
      "bar_count": 5, "expected_rows": 5}],
    "20260928", "STAGE_0930_0935", "a" * 64,
)
published = publish_selection(store_root, envelope, market="A_SHARE")
verified = SelectionStore(store_root).read_verified("20260928", "STAGE_0930_0935", "A_SHARE")
assert verified == published == envelope
run_id = verified["run_id"]
artifact = store_root / "selection_runs" / "20260928" / "A_SHARE_SELECTION_STAGE_0930_0935" / run_id / "artifact.csv"
artifact.write_bytes(artifact.read_bytes() + b"tampered\n")
try:
    SelectionStore(store_root).read_verified("20260928", "STAGE_0930_0935", "A_SHARE")
except SelectionError as error:
    assert "artifact SHA mismatch" in str(error)
else:
    raise AssertionError("tampered packaged selection artifact was accepted")
print(json.dumps({"roundtrip": "PASS", "tamper_rejected": True, "run_id": run_id}))
'''
    completed = subprocess.run(
        [str(Path(sys.executable)), "-I", "-c", script, str(candidate_app), str(store_root)],
        cwd=candidate_app,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["roundtrip"] == "PASS"
    assert result["tamper_rejected"] is True
    assert receipt["stage_overlay_paths"] == list(stage_builder.STAGE_SERVICE_OVERLAY_PATHS)


def test_legacy_non_strict_partial_overlay_remains_supported(tmp_path, monkeypatch):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_strict_source(tmp_path, strict=False)
    baseline_release, stage_plist = _write_synthetic_active_release(tmp_path, source_config)
    candidate_root = tmp_path / "candidates" / "legacy-partial-stage"
    receipt_path = tmp_path / "evidence" / "legacy-receipt.json"
    overlays = (
        "ops/run_stage_center_nodes.py",
        "stage_center/runner.py",
        "stage_center_tick_config.json",
    )

    receipt = builder.build_stage_service_candidate(
        source_root=source_root,
        candidate_root=candidate_root,
        stage_plist_path=stage_plist,
        runtime_python=Path(sys.executable),
        release_id="legacy-stage-fixture",
        formal_release_root=tmp_path / "formal",
        receipt_path=receipt_path,
        baseline_release_root=baseline_release,
        overlay_paths=overlays,
    )

    manifest = json.loads((candidate_root / "release-manifest.json").read_text())
    assert receipt["stage_overlay_paths"] == list(overlays)
    assert manifest["source"]["stage_overlay"]["non_overlay_active_release_bytes_preserved"] is True
    assert (candidate_root / "app" / "manager" / "state-reference.json").read_text() == (
        '{"root":"fixture-manager-root"}\n'
    )
    assert receipt["activation_status"] == "NOT_ACTIVATED"


def test_legacy_default_uses_pinned_runtime_closure_without_strict_only_sources(tmp_path, monkeypatch):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_original_legacy_source(tmp_path)
    assert not (source_root / "ops/run_stage_center_worker.py").exists()
    assert not (source_root / "stage_center/commit_store.py").exists()
    baseline_release, stage_plist = _write_synthetic_active_release(tmp_path, source_config)
    candidate_root = tmp_path / "candidates" / "legacy-default-stage"
    receipt_path = tmp_path / "evidence" / "legacy-default-receipt.json"

    receipt = builder.build_stage_service_candidate(
        source_root=source_root,
        candidate_root=candidate_root,
        stage_plist_path=stage_plist,
        runtime_python=Path(sys.executable),
        release_id="legacy-default-fixture",
        formal_release_root=tmp_path / "formal",
        receipt_path=receipt_path,
        baseline_release_root=baseline_release,
    )

    assert receipt["stage_overlay_paths"] == list(stage_builder.LEGACY_STAGE_SERVICE_OVERLAY_PATHS)
    assert "ops/run_stage_center_worker.py" not in receipt["stage_overlay_paths"]
    assert "stage_center/commit_store.py" not in receipt["stage_overlay_paths"]
    assert "domains/task_status.py" not in receipt["stage_overlay_paths"]
    manifest = json.loads((candidate_root / "release-manifest.json").read_text())
    assert [entry["path"] for entry in manifest["source"]["stage_overlay"]["entries"]] == list(
        stage_builder.LEGACY_STAGE_SERVICE_OVERLAY_PATHS
    )


def test_legacy_default_rejects_missing_pinned_closure_source_before_candidate_creation(
    tmp_path, monkeypatch,
):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_original_legacy_source(tmp_path)
    missing_relative = stage_builder.STAGE_SERVICE_RELEASE_CLOSURE_PATHS[0]
    (source_root / missing_relative).unlink()
    baseline_release, stage_plist = _write_synthetic_active_release(tmp_path, source_config)
    candidate_root = tmp_path / "candidates" / "missing-pinned-closure-source"
    receipt_path = tmp_path / "evidence" / "missing-pinned-closure-source.json"

    with pytest.raises(FileNotFoundError, match="Stage overlay closure source is missing"):
        builder.build_stage_service_candidate(
            source_root=source_root,
            candidate_root=candidate_root,
            stage_plist_path=stage_plist,
            runtime_python=Path(sys.executable),
            release_id="missing-pinned-closure-source",
            formal_release_root=tmp_path / "formal",
            receipt_path=receipt_path,
            baseline_release_root=baseline_release,
        )

    assert not candidate_root.exists()
    assert not receipt_path.exists()


def test_legacy_default_rejects_wrong_pinned_closure_sha_before_candidate_creation(
    tmp_path, monkeypatch,
):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_original_legacy_source(tmp_path)
    wrong_relative = stage_builder.STAGE_SERVICE_RELEASE_CLOSURE_PATHS[0]
    wrong_source = source_root / wrong_relative
    wrong_source.write_bytes(wrong_source.read_bytes() + b"\n")
    baseline_release, stage_plist = _write_synthetic_active_release(tmp_path, source_config)
    candidate_root = tmp_path / "candidates" / "wrong-pinned-closure-sha"
    receipt_path = tmp_path / "evidence" / "wrong-pinned-closure-sha.json"

    with pytest.raises(ValueError, match="Stage overlay closure source SHA-256 mismatch"):
        builder.build_stage_service_candidate(
            source_root=source_root,
            candidate_root=candidate_root,
            stage_plist_path=stage_plist,
            runtime_python=Path(sys.executable),
            release_id="wrong-pinned-closure-sha",
            formal_release_root=tmp_path / "formal",
            receipt_path=receipt_path,
            baseline_release_root=baseline_release,
        )

    assert not candidate_root.exists()
    assert not receipt_path.exists()


def test_hk_deadline_candidate_preserves_exact_service_identity_and_deadline_only_argv(
    tmp_path, monkeypatch,
):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_strict_source(tmp_path, strict=False)
    deadline_label = stage_builder.STAGE_DEADLINE_SERVICE_LABEL
    baseline_release, stage_plist = _write_synthetic_active_release(
        tmp_path,
        source_config,
        service_label=deadline_label,
        deadline_only=True,
    )
    candidate_root = tmp_path / "candidates" / "hk-deadline-stage"
    receipt = builder.build_stage_service_candidate(
        source_root=source_root,
        candidate_root=candidate_root,
        stage_plist_path=stage_plist,
        runtime_python=Path(sys.executable),
        release_id="hk-deadline-stage-fixture",
        formal_release_root=tmp_path / "formal",
        receipt_path=tmp_path / "evidence" / "hk-deadline-stage.json",
        baseline_release_root=baseline_release,
    )

    binding = receipt["service_binding"]
    assert binding["label"] == deadline_label
    assert binding["deadline_only"] is True
    staged_plist = plistlib.loads(Path(binding["path"]).read_bytes())
    assert staged_plist["Label"] == deadline_label
    assert staged_plist["ProgramArguments"][-1] == "--deadline-only"
    assert Path(staged_plist["ProgramArguments"][4]).name == "stage_center_tick_config.json"
    manifest = json.loads((candidate_root / "release-manifest.json").read_text())
    assert manifest["stage_service"]["label"] == deadline_label
    assert manifest["stage_service"]["deadline_only"] is True
    assert manifest["data_paths"]["deployed_release_reference"]["status"] == (
        "READ_ONLY_REFERENCE_CAPTURED"
    )


@pytest.mark.parametrize(
    ("service_label", "deadline_only"),
    [
        ("com.lexi.stage-center.other", False),
        (stage_builder.STAGE_DEADLINE_SERVICE_LABEL, False),
        (builder.STAGE_SERVICE_LABEL, True),
    ],
)
def test_stage_candidate_rejects_unknown_label_or_wrong_deadline_argv_before_creation(
    tmp_path, monkeypatch, service_label, deadline_only,
):
    _patch_offline_builder(monkeypatch)
    source_root, source_config = _copy_strict_source(tmp_path, strict=False)
    baseline_release, stage_plist = _write_synthetic_active_release(
        tmp_path,
        source_config,
        service_label=service_label,
        deadline_only=deadline_only,
    )
    candidate_root = tmp_path / "candidates" / "wrong-stage-service-identity"
    receipt_path = tmp_path / "evidence" / "wrong-stage-service-identity.json"
    expected_error = (
        "Stage source LaunchAgent label mismatch"
        if service_label == "com.lexi.stage-center.other"
        else "Stage active plist arguments are invalid"
    )

    with pytest.raises(ValueError, match=expected_error):
        builder.build_stage_service_candidate(
            source_root=source_root,
            candidate_root=candidate_root,
            stage_plist_path=stage_plist,
            runtime_python=Path(sys.executable),
            release_id="wrong-stage-service-identity",
            formal_release_root=tmp_path / "formal",
            receipt_path=receipt_path,
            baseline_release_root=baseline_release,
        )

    assert not candidate_root.exists()
    assert not receipt_path.exists()


def test_stage_cli_default_defers_overlay_selection_to_effective_config(monkeypatch, tmp_path, capsys):
    captured = {}

    def fake_stage_builder(**kwargs):
        captured.update(kwargs)
        return {"stage_overlay_paths": []}

    monkeypatch.setattr(builder, "build_stage_service_candidate", fake_stage_builder)
    result = builder.main([
        "--source-root", str(tmp_path / "source"),
        "--candidate-root", str(tmp_path / "candidate"),
        "--release-id", "cli-overlay-fixture",
        "--stage-service-candidate",
        "--stage-plist", str(tmp_path / "stage.plist"),
        "--formal-release-root", str(tmp_path / "formal"),
    ])
    capsys.readouterr()

    assert result == 0
    assert captured["overlay_paths"] is None
