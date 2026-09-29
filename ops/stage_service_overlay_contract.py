"""Reviewed source closure for the strict Stage service overlay."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


STAGE_SERVICE_LABEL = "com.lexi.stage-center.scheduler"
STAGE_DEADLINE_SERVICE_LABEL = "com.lexi.stage-center.hk-deadline"
STAGE_SERVICE_LABELS = (STAGE_SERVICE_LABEL, STAGE_DEADLINE_SERVICE_LABEL)
STAGE_DATA_PATH_KEYS = (
    "candidate_acquisition_root",
    "raw_root",
    "selection_root",
    "receipt_root",
    "v4_research_data_root",
    "preselection_source_root",
    "hk_d1_root",
    "hk_second_filter_root",
    "hk_full_universe_root",
    "a_auction_root",
    "hk_auction_root",
    "hk_stage_replay_root",
    "a_research_panel_receipt_root",
)
STAGE_DISTRIBUTIONS = ("futu-api", "pytdx", "pandas", "pyarrow", "numpy")

# Bounded closure derived from the current Stage legacy entry imports plus the
# pinned 68-file runtime readback. The sibling receipt records per-active-base
# SAME/DIFF/MISSING classification. The 48 newly admitted paths and two
# existing Stage roots changed by the reviewed backend sync are SHA-pinned.
STAGE_SERVICE_RELEASE_CLOSURE_SHA256 = {
    'infrastructure/_stage_acquisition_universe_commit_parts/__init__.py': '29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8',
    'infrastructure/_stage_acquisition_universe_commit_parts/_namespace.py': '45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1',
    'infrastructure/_stage_acquisition_universe_commit_parts/artifact_validation.py': '82a2ad10a6c2c83ca49ca325790eac037a56bbce5f02e6c45dbe0d516bf843a9',
    'infrastructure/_stage_acquisition_universe_commit_parts/commit_metadata.py': '5e00058b431e77ccda2ab5f0a85ab69fc385f5ec6c45790fa5037b8dad6f7710',
    'infrastructure/_stage_acquisition_universe_commit_parts/current_verification.py': '3c2971a8d2301c7842fd5af79518828aa8e5013edb0864bd1bb21a254e96e99c',
    'infrastructure/_stage_acquisition_universe_commit_parts/identity_primitives.py': 'c54541390c68db1f5e602a3d0f5229be4d40c36931f89f4cd9efb42ff0c74c0a',
    'infrastructure/_stage_acquisition_universe_commit_parts/initial_publication.py': '043e09b84c72b6189a01f035c55b20c0171f6c2beba8cccd265a276d600922ab',
    'infrastructure/_stage_acquisition_universe_commit_parts/orphan_recovery.py': 'a79541afbcbda69264fb2cbd3bcda9b533613540bb8ee3287b31e9cf13e57e35',
    'infrastructure/_stage_acquisition_universe_commit_parts/successor_publication.py': '8dbb2dc66ad14b19395a455f6080116c72262234d189134969cee35718bc2b71',
    'infrastructure/_stage_acquisition_universe_commit_parts/supersession_receipts.py': '2e775c05d8b1a06077d8efa4b1e24b6201f4ac4155ebe96bcefd967979126dab',
    'infrastructure/_stage_acquisition_universe_commit_parts/supersession_verification.py': '194d422597e296c991118285552616618a8e4d09403748dc704dca4ac2b0f317',
    'infrastructure/_stage_acquisition_universe_contracts_parts/__init__.py': '29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8',
    'infrastructure/_stage_acquisition_universe_contracts_parts/_namespace.py': '45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1',
    'infrastructure/_stage_acquisition_universe_contracts_parts/frozen_types.py': 'b2d12a2395e7eee37b507491a69e7b41faec9a956060de549cbb86d7ce34898e',
    'infrastructure/_stage_acquisition_universe_contracts_parts/primitives.py': '74a3ec19a475aadce3f320104b04a9927982b4701dd90722efe6ec71e645e6f0',
    'infrastructure/_stage_acquisition_universe_contracts_parts/rows_metadata.py': 'bbd01c448a433c27c9eb6029144cb7aaf37ee20fe0fa5deda6fe83b34748641a',
    'infrastructure/_stage_acquisition_universe_contracts_parts/snapshot_aggregation.py': '7026f222987d2929e40492e7a45aafe277a091a60fa346e7e3c10d34d76e6031',
    'infrastructure/_stage_acquisition_universe_contracts_parts/snapshot_provenance.py': '996be2450136317f4c21880edba8e567fcb130d9cfc01767e0ae6140ca6e0ecd',
    'infrastructure/_stage_acquisition_universe_contracts_parts/snapshot_publication.py': 'e4bfd622b1e514e86afe660a0d677ec16a9183703be1f51f3631062eb3103573',
    'infrastructure/_stage_acquisition_universe_contracts_parts/snapshot_verification.py': 'c69b5b486c65c7b3da124ecb41557cad412cdd9cf1e68bf04c2abc3576a211dc',
    'infrastructure/_stage_acquisition_universe_contracts_parts/strict_artifact.py': '482366aced74e8db9f384c3497728ef66d32ed62a6bc8d448c2cddd95b604a57',
    'infrastructure/preselection_pool_readers.py': '949b16526e2b55ae23d121ca3909b4d33509483164d1899e65c94aef6d5781c1',
    'infrastructure/preselection_pool_sources.py': 'cc683561201453e3f7ca975b2b7cdb6a3836b1ecbe63e001a5abd181f38813d6',
    'infrastructure/preselection_pool_transactions.py': '22cca047d8d2da3ec9b1c4d3d18fd09026887ee48a95868757bfc598d094d58d',
    'infrastructure/scope_gate.py': '5620d1ee89fbae998d4c801c2a7c4cffac50f890ad0b6951f99230c591dcff68',
    'infrastructure/stage_acquisition_universe_commit.py': '373d011f299d2a1d7afb173ac7b107ac54d92d036cea7127dadba4873bcf56a3',
    'infrastructure/stage_acquisition_universe_contracts.py': 'ab23a06700d080044d0c372997544b2ab35365ca96332c53170af6788aabc8f9',
    'infrastructure/stage_source_roots.py': 'daf2d43ea482e364d5ad2a22c91be1676e39be9e8b2ad2c2125ddc75d617dc5d',
    'ops/_run_stage_center_nodes_parts/__init__.py': '29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8',
    'ops/_run_stage_center_nodes_parts/_namespace.py': '45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1',
    'ops/_run_stage_center_nodes_parts/node_entry.py': '54defb0f45adbafcf4b661611f41d0b43d89abf492d89d587c28962eff9b36fe',
    'ops/_run_stage_center_nodes_parts/stage_dispatch.py': 'df6221a177d82f0fd683896b3ef21cd66cd7a8a4b6c6c8b95571f277108d52fe',
    'ops/materialize_stage_acquisition_universe.py': '18adabeebc75a28f49f48778ca513ed3d703b12dee40446b8067dff49966f1fe',
    'stage_center/_live_collectors_parts/__init__.py': '29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8',
    'stage_center/_live_collectors_parts/_namespace.py': '45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1',
    'stage_center/_live_collectors_parts/hk_active_snapshot.py': '5079d283c25d8bc778e749e29b5c590eae25d90b3a9d5ffc785e32ce02e5f5b9',
    'stage_center/_live_collectors_parts/temporal_validation.py': '61c8fec0021fb66356cf31791a5bc3af576681fa1e576bbf142463b581dc2961',
    'stage_center/_runner_parts/__init__.py': '29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8',
    'stage_center/_runner_parts/_namespace.py': '45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1',
    'stage_center/_runner_parts/slot_lock.py': 'f90d3c8e3fba34d157bf45e1f544e9169a575931a3f2f33340e97c25879f5c1d',
    'stage_center/_selection_parts/__init__.py': 'b56739ecc4a80eaa081f3ea124cf3199683fd470d71a770c9f91cc14de128140',
    'stage_center/_selection_parts/_namespace.py': '45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1',
    'stage_center/_selection_parts/schema_values.py': '80b0c21556c78c89132a08ca24eb80b5a211791719cb54801497dbe74472e458',
    'stage_center/attempt_evidence.py': 'f98a9070ade0c26a3cfa0bf60acd4798ec011330ca83bc172c64856bd88dc1bf',
    'stage_center/calendar.py': '31fed97066d9b804a71f15c48d4e0f8baa5d9af621e1d81dc0340fd6619e4099',
    'stage_center/consumer.py': '9e3a864c74eaec6c616b911b09c167c8cb407db8435343c1b522de4f4c9459eb',
    'stage_center/raw_store.py': '15052b23c62d38b65d65b96bf3b837782ebfa6fca7fe83f7c1d9374400bbdbde',
    'stage_center/scheduler.py': 'e56651ec7bb481b28e383cb403d60ba48747ddf7426f9fb380f5ae24fc3a37a4',
    'stage_center/runner.py': '648fe7af52df1b4eba31802361f9af2d03decbbebb3286ecc7a5dc0b06523205',
    'domains/task_status.py': '047cfb2b6a8c165857b2841f137a86c9587a1a6e81199efdf71d508d05589300',
}
STAGE_SERVICE_RELEASE_CLOSURE_PATHS = tuple(STAGE_SERVICE_RELEASE_CLOSURE_SHA256)


# Keep the acquisition commit and its contract module from the verified active
# R1 release. The older workspace copies are incompatible with the active
# materializer: they drop its constructor/source-read-lease contract and a
# helper imported by the R1 commit implementation.
STAGE_SERVICE_BASE_OVERLAY_PATHS = (
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
    "ops/run_stage_center_worker.py",
    "stage_center/commit_store.py",
    "stage_center/consumer.py",
    "ops/run_stage_center_tick.py",
    "domains/preselection.py",
    "domains/task_status.py",
)

LEGACY_STAGE_SERVICE_BASE_OVERLAY_PATHS = (
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

STAGE_SERVICE_RELEASE_CLOSURE_ROOT_PIN_PATHS = (
    "stage_center/runner.py",
    "domains/task_status.py",
)
STAGE_SERVICE_RELEASE_CLOSURE_ADDED_PATHS = tuple(
    relative for relative in STAGE_SERVICE_RELEASE_CLOSURE_PATHS
    if relative not in STAGE_SERVICE_RELEASE_CLOSURE_ROOT_PIN_PATHS
    and relative not in LEGACY_STAGE_SERVICE_BASE_OVERLAY_PATHS
)

STAGE_SERVICE_OVERLAY_PATHS = tuple(dict.fromkeys((
    *STAGE_SERVICE_BASE_OVERLAY_PATHS,
    *STAGE_SERVICE_RELEASE_CLOSURE_ADDED_PATHS,
)))
LEGACY_STAGE_SERVICE_OVERLAY_PATHS = tuple(dict.fromkeys((
    *LEGACY_STAGE_SERVICE_BASE_OVERLAY_PATHS,
    *STAGE_SERVICE_RELEASE_CLOSURE_ADDED_PATHS,
)))

STRICT_STAGE_SERVICE_OVERLAY_PATHS = (
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

def require_stage_overlay_source_hashes(
    *, source_root: Path, overlay_paths: Sequence[str],
) -> None:
    """Require exact source bytes for every selected Stage closure path."""
    selected = set(overlay_paths)
    for relative in STAGE_SERVICE_RELEASE_CLOSURE_PATHS:
        if relative not in selected:
            continue
        path = source_root / relative
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(
                f"Stage overlay closure source is missing or not a regular file: {relative}"
            )
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = STAGE_SERVICE_RELEASE_CLOSURE_SHA256[relative]
        if actual != expected:
            raise ValueError(
                f"Stage overlay closure source SHA-256 mismatch: {relative}; "
                f"expected {expected}, got {actual}"
            )


def require_complete_strict_stage_overlay(
    *,
    source_root: Path,
    overlay_paths: Sequence[str],
    effective_config: Mapping[str, Any],
) -> None:
    """Require the reviewed nine-file cohort when the final config is strict."""
    if effective_config.get("publication_mode") != "strict_commit_required":
        return

    selected = set(overlay_paths)
    required = set(STRICT_STAGE_SERVICE_OVERLAY_PATHS)
    missing_selection = sorted(required - selected)
    if missing_selection:
        raise ValueError(
            "strict Stage overlay requires the complete reviewed cohort; "
            f"missing selected paths: {missing_selection}"
        )
    missing_sources = sorted(
        relative for relative in STRICT_STAGE_SERVICE_OVERLAY_PATHS
        if not (source_root / relative).is_file() or (source_root / relative).is_symlink()
    )
    if missing_sources:
        raise FileNotFoundError(
            "strict Stage overlay source cohort is incomplete; "
            f"missing regular files: {missing_sources}"
        )


def _merge_active_stage_config(source_config: Mapping[str, Any], active_config: Mapping[str, Any]) -> dict[str, Any]:
    """Keep current Stage roots while retaining the active r1 D1 resolver root."""
    merged = deepcopy(dict(source_config))
    active_root = active_config.get("preselection_source_root")
    source_root = merged.get("preselection_source_root")
    if not isinstance(active_root, str) or not active_root.strip():
        raise ValueError("Stage active preselection_source_root is required")
    if source_root not in (None, "") and str(source_root) != active_root:
        raise ValueError("Stage source preselection_source_root conflicts with active release")
    merged["preselection_source_root"] = active_root
    return merged


def _effective_stage_config(
    *,
    source_root: Path,
    overlay_paths: Sequence[str],
    active_config: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Resolve the config bytes the candidate will use before package creation."""
    config_relative = "stage_center_tick_config.json"
    if config_relative not in overlay_paths:
        return active_config

    config_path = source_root / config_relative
    if not config_path.is_file() or config_path.is_symlink():
        raise FileNotFoundError(
            f"Stage overlay source must be a regular file: {config_relative}"
        )
    source_config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(source_config, dict):
        raise ValueError("Stage source config must be a JSON object")
    return _merge_active_stage_config(source_config, active_config)


def _active_stage_manifest_identity(
    manifest: object, *, app_root: Path, release_root: Path,
) -> dict[str, str]:
    """Read, never rewrite, flat legacy or Stage-v2 nested release identity.

    Stage v2 requires its complete candidate identity. Optional legacy aliases
    must agree; a correct alias never rescues a missing/conflicting primary
    identity. Source/integration_base identifies another release, not this one.
    """
    if not isinstance(manifest, dict):
        raise ValueError("Stage active release manifest must be an object")
    fields = ("app_root", "release_root", "release_id")
    nested_fields = {"app_root": "app_root", "release_root": "root", "release_id": "release_id"}
    candidate = manifest.get("candidate")
    is_v2 = manifest.get("schema_version") == "v4.stage_service_candidate.v2"
    if "candidate" in manifest and not isinstance(candidate, dict):
        raise ValueError("Stage active release candidate identity must be an object")
    if is_v2 and not isinstance(candidate, dict):
        raise ValueError("Stage v2 requires candidate identity")
    primary = candidate if is_v2 else manifest
    identity: dict[str, str] = {}
    for field in fields:
        key = nested_fields[field] if is_v2 else field
        value = primary.get(key)
        if (not isinstance(value, str) or not value.strip()
                or value != value.strip() or "\x00" in value):
            raise ValueError(f"Stage active release identity missing or invalid: {field}")
        identity[field] = value
    # Validate every declared representation instead of using `a or b`.
    for field in fields:
        if field in manifest and manifest[field] != identity[field]:
            raise ValueError(f"Stage active release identity conflict: {field}")
    if isinstance(candidate, dict) and any(key in candidate for key in nested_fields.values()):
        for field, key in nested_fields.items():
            if candidate.get(key) != identity[field]:
                raise ValueError(f"Stage active release identity conflict: candidate.{key}")
    if identity["app_root"] != str(app_root) or not Path(identity["app_root"]).is_absolute():
        raise ValueError("Stage active release manifest app_root mismatch")
    if identity["release_root"] != str(release_root) or not Path(identity["release_root"]).is_absolute():
        raise ValueError("Stage active release manifest release_root mismatch")
    return identity


def _validate_stage_manifest_bindings(
    identity: Mapping[str, str], *, environment: object, active_config: Mapping[str, Any],
    manifest_path: Path, manifest_sha256: str,
) -> None:
    """Check explicitly declared bindings; absent legacy env keys stay optional."""
    if environment is None:
        environment = {}
    if not isinstance(environment, dict):
        raise ValueError("Stage active release environment binding must be an object")
    expected = {
        "V35_RELEASE_ID": identity["release_id"],
        "V35_RELEASE_MANIFEST_PATH": str(manifest_path),
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha256,
    }
    for key, value in expected.items():
        if key in environment and environment[key] != value:
            raise ValueError(f"Stage active release binding mismatch: {key}")
    if "release_id" in active_config and active_config["release_id"] != identity["release_id"]:
        raise ValueError("Stage active release binding mismatch: config.release_id")
