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

# This one observed Stage R4 release has a legacy metadata mismatch: its
# LaunchAgent and release manifest bind R4, while the exact R4 config file
# still says R1.  Compatibility is allowed only for this immutable manifest /
# config byte pair.  New candidates receive their own consistent identities.
PINNED_LEGACY_STAGE_MANIFEST_SHA256 = "f6d40837d72f17575580bf2c3547d06c42d5cf6af350f2dd9b43be54e1488eda"
PINNED_LEGACY_STAGE_CONFIG_SHA256 = "437b1db3b4ac9f38e6c0e28ad002fa2d22bfcbaba139f4d2290ce35eb898ed54"
PINNED_LEGACY_STAGE_RELEASE_ID = "futu-primary-afternoon-20261012-r4"
PINNED_LEGACY_STAGE_CONFIG_RELEASE_ID = "afternoon-auto-stages-20261012-r1"
PINNED_LEGACY_STAGE_CACHE_ENTRY_COUNT = 100
PINNED_LEGACY_STAGE_CACHE_INVENTORY_SHA256 = "94a1c3f4824725b242099c7b7ef5869e342e9fb15d03e89fe220c0d5fe300921"
PINNED_LEGACY_STAGE_DECLARED_INVENTORY_SHA256 = "f2e6712060bf652d16c80d2d0fb34552f3459dcec7018c983b3f569eb27bbd07"
PINNED_LEGACY_STAGE_RECOMPUTED_INVENTORY_SHA256 = "e0219559dac41358374c99b7b9477a463a5a2f3538f145795344e3c90ffc8699"

# Bounded closure derived from the current Stage legacy entry imports plus the
# pinned 68-file runtime readback. The sibling receipt records per-active-base
# SAME/DIFF/MISSING classification. The 48 newly admitted paths and two
# existing Stage roots changed by the reviewed backend sync are SHA-pinned.
STAGE_SERVICE_RELEASE_CLOSURE_SHA256 = {
    'infrastructure/_stage_acquisition_universe_commit_parts/__init__.py': '29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8',
    'infrastructure/_stage_acquisition_universe_commit_parts/_namespace.py': '45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1',
    # Exact bytes adopted from the fixed UNKNOWN_CONCURRENT_OWNER snapshot;
    # the candidate builder passes that snapshot as a source override.
    'infrastructure/_stage_acquisition_universe_commit_parts/artifact_validation.py': '56a8bd7cb35658865ba92caf445ed3089d05c822f01bf6b86af021580a4e6982',
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
    'infrastructure/_stage_acquisition_universe_contracts_parts/snapshot_provenance.py': 'ddc0250817f92fb5b07998a1e8b82e772551d7e384647f2e5595cb78571bc8e7',
    'infrastructure/_stage_acquisition_universe_contracts_parts/snapshot_publication.py': 'b863eed25f69e1c2e113968082a8e9e44eb018e398076da82373cb5dc71dba1d',
    'infrastructure/_stage_acquisition_universe_contracts_parts/snapshot_verification.py': 'c69b5b486c65c7b3da124ecb41557cad412cdd9cf1e68bf04c2abc3576a211dc',
    'infrastructure/_stage_acquisition_universe_contracts_parts/strict_artifact.py': 'c7f43ee2cf92bcfc5580c61d7395dd72bf54abc05a8a0e1dfba7fec274d8e439',
    'infrastructure/preselection_pool_store.py': '7a2a213cecad1ed1cfc96f6c9c0dd18b960fcbd9c932cbe0be444a35952502e1',
    'infrastructure/preselection_pool_readers.py': '7b153abba65eb2387a3f2d87c96466ab5cf38aa331f51b4661940f4c9149c9cc',
    'infrastructure/preselection_pool_sources.py': '0de0adb98b35fe7210d4026fa9f3fc4af254ac6ea68726e76e6ea357e177f2d7',
    'infrastructure/preselection_pool_transactions.py': '22cca047d8d2da3ec9b1c4d3d18fd09026887ee48a95868757bfc598d094d58d',
    'infrastructure/scope_gate.py': '5620d1ee89fbae998d4c801c2a7c4cffac50f890ad0b6951f99230c591dcff68',
    'infrastructure/stage_acquisition_universe_commit.py': '373d011f299d2a1d7afb173ac7b107ac54d92d036cea7127dadba4873bcf56a3',
    'infrastructure/stage_acquisition_universe_contracts.py': 'ab23a06700d080044d0c372997544b2ab35365ca96332c53170af6788aabc8f9',
    'infrastructure/stage_source_roots.py': 'daf2d43ea482e364d5ad2a22c91be1676e39be9e8b2ad2c2125ddc75d617dc5d',
    'ops/_run_stage_center_nodes_parts/__init__.py': '29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8',
    'ops/_run_stage_center_nodes_parts/_namespace.py': '45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1',
    'ops/_run_stage_center_nodes_parts/node_entry.py': '69bd2eebb195e4eecb75fd7892b0ddb43797cd32b46df41e149f35e59ea2ef19',
    'ops/_run_stage_center_nodes_parts/stage_dispatch.py': '2bbe352d40309befa7eb64521fe74d6054611421cb749a7b11dfb98ae78bfaa7',
    'ops/materialize_stage_acquisition_universe.py': '18adabeebc75a28f49f48778ca513ed3d703b12dee40446b8067dff49966f1fe',
    'stage_center/_live_collectors_parts/__init__.py': '29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8',
    'stage_center/_live_collectors_parts/_namespace.py': '45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1',
    'stage_center/_live_collectors_parts/hk_active_snapshot.py': '5079d283c25d8bc778e749e29b5c590eae25d90b3a9d5ffc785e32ce02e5f5b9',
    'stage_center/_live_collectors_parts/temporal_validation.py': '61c8fec0021fb66356cf31791a5bc3af576681fa1e576bbf142463b581dc2961',
    'stage_center/_runner_parts/__init__.py': '29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8',
    'stage_center/_runner_parts/_namespace.py': '45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1',
    'stage_center/_runner_parts/slot_lock.py': 'f90d3c8e3fba34d157bf45e1f544e9169a575931a3f2f33340e97c25879f5c1d',
    'stage_center/_runner_parts/slot_execution.py': '717e1b4a888fd9504b10514cd2064a259e842942c482a7497831a5db2962fcb7',
    'stage_center/_runner_parts/row_evidence.py': 'fd385163fc563d3b4f2c19389fc277e962ee424a0a459c164fbcf8b1669a5b42',
    'stage_center/_selection_parts/__init__.py': 'b56739ecc4a80eaa081f3ea124cf3199683fd470d71a770c9f91cc14de128140',
    'stage_center/_selection_parts/_namespace.py': '45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1',
    'stage_center/_selection_parts/schema_values.py': '80b0c21556c78c89132a08ca24eb80b5a211791719cb54801497dbe74472e458',
    'stage_center/attempt_evidence.py': 'f98a9070ade0c26a3cfa0bf60acd4798ec011330ca83bc172c64856bd88dc1bf',
    'stage_center/candidate_input.py': 'd35f9db18aedc5ce5e1a62cac9b773b7c227ebf7ecbeacdf53bcb8af8cd315a5',
    'stage_center/calendar.py': '31fed97066d9b804a71f15c48d4e0f8baa5d9af621e1d81dc0340fd6619e4099',
    'stage_center/consumer.py': '9e3a864c74eaec6c616b911b09c167c8cb407db8435343c1b522de4f4c9459eb',
    'stage_center/raw_store.py': '800acddb67a3e234342b7ab84cd26849018bc0b24247d5c4a26414a6d1bc6248',
    'stage_center/scheduler.py': 'db110aba2fe504213591330000120b660cff04292728b5325711e2fa6799e7b0',
    'stage_center/runner.py': '1bb6363dfa522cdc05f8d1d1e727bf120f4daadbb2579600fc465a6d12e11663',
    'domains/preselection.py': '85c75d206e5edb66c5dc3f34c8e9d0c1889e73c49950b627fb63c4f12ae9be18',
    'domains/_preselection_parts/__init__.py': '29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8',
    'domains/_preselection_parts/_namespace.py': '45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1',
    'domains/_preselection_parts/date_catalog.py': 'f816a30e8aa99b3f55f077d884379f36beef5f6f25c1d748ccb8df2a2094622f',
    'domains/_preselection_parts/independent_projection.py': '0d106ae33b25f7a44e846e7fc1250c0bdb442d08e752b6f8f495edac359d524c',
    'domains/_preselection_parts/pagination_metadata.py': 'b1ca5157aa6b6fc082c8a85e25d1132ced381264f3591458b41feb3d27ba3afc',
    'domains/_preselection_parts/pool_assembly.py': '408df356fc7d9806fbb2372fcfd3da6a7afffd05d3e140d9fddc09c347d5ff4e',
    'domains/_preselection_parts/review_fupan.py': '33cd17df2293b94604915dc4e27b4d16fcb97904f403a641b354bc870e06381c',
    'domains/_preselection_parts/review_stage7.py': '86cd191a5212c4986bac45f880b5ef251590863da3802b6523170bc00c24169b',
    'domains/_preselection_parts/source_validation.py': 'ba650bb72e78aec6c006faf45804ea670c8fa9c187a45e32b563d31be4605d1d',
    'domains/task_status.py': '17254ea0e50e9f14cf28bebf64cf867494d434bc527f112e99e00cc81cfbe363',
}
STAGE_SERVICE_RELEASE_CLOSURE_PATHS = tuple(STAGE_SERVICE_RELEASE_CLOSURE_SHA256)
STAGE_SERVICE_BASE_PRESERVED_SOURCE_PATHS = {
    'domains/task_status.py': '17254ea0e50e9f14cf28bebf64cf867494d434bc527f112e99e00cc81cfbe363',
    'ops/_run_stage_center_nodes_parts/node_entry.py': '69bd2eebb195e4eecb75fd7892b0ddb43797cd32b46df41e149f35e59ea2ef19',
    'ops/_run_stage_center_nodes_parts/stage_dispatch.py': '2bbe352d40309befa7eb64521fe74d6054611421cb749a7b11dfb98ae78bfaa7',
    'ops/recover_selection_observations.py': '1d87d530176d12f0ff11133fec8f569543eb6444e8be9a5c7be0e1db15b9e34e',
    'ops/run_stage_center_nodes.py': '8e9ca56aca8a21950590abe83ef305e46a022490eb61f48e0c5d19c2493e1772',
    'ops/run_stage_center_tick.py': '4eb8e1a3be0e3780ff9cb62417c695c5aab67948f224db462d3f6e3a67299f42',
    'stage_center/consumer.py': '9e3a864c74eaec6c616b911b09c167c8cb407db8435343c1b522de4f4c9459eb',
    'stage_center/end_to_end_deadline.py': 'f25d91cf1eaf4ea7d1a9a57fc1f8288d14d98536a63dee16467550974b2a812e',
    'stage_center/formula_margin_shadow.py': '5e637c8650a7779b24148d6341743765045b252804bc450f755a9f448acdbb2b',
    'stage_center/hk_stage8/__init__.py': 'd33f9f7ba2135f35073c92fdae1cd8b877f1fa9271f4c1c22217c1e969455f0b',
    'stage_center/hk_stage8/builders.py': '231b8c0acc1092663b3236ad0415242280c4951b17a0aa094b632f7be0fe5a7c',
    'stage_center/hk_stage8/precapture.py': '09e2140a6a3dd5516556193dec4a4e67b7d5db425be2282f187ea8c819d1f002',
    'stage_center/hk_stage8/rtdata.py': 'a85317c29df499162c7c805be19e89e198f77ad1d51811912da0c29d27bb8547',
    'stage_center/hk_stage8/snapshot.py': 'd1658e72a03a6842c2e6b1b3ae63f6889aa00f28c69ad0a7aa5c7400bf6f5267',
    'stage_center/input_contracts.py': '9521a336709286ab301368a70e2c99f6db6a8ffe288347977328619de7611fd2',
    'stage_center/live_collectors.py': '82a08c2bbe286184e1a224d0a44e576d0f812f1ec2929ded303ab191a1d554bf',
    'stage_center/raw_store.py': '800acddb67a3e234342b7ab84cd26849018bc0b24247d5c4a26414a6d1bc6248',
    'stage_center/runner.py': '1bb6363dfa522cdc05f8d1d1e727bf120f4daadbb2579600fc465a6d12e11663',
    'stage_center/scheduler.py': 'db110aba2fe504213591330000120b660cff04292728b5325711e2fa6799e7b0',
    'stage_center/selection.py': '8fa7d50a4b51302ddc61479c2a9cd865aedf112d437f8d01a42bbae73e235957',
    'stage_center_tick_config.json': '437b1db3b4ac9f38e6c0e28ad002fa2d22bfcbaba139f4d2290ce35eb898ed54',
}


# Keep the acquisition commit and its contract module from the verified active
# R1 release. The older workspace copies are incompatible with the active
# materializer: they drop its constructor/source-read-lease contract and a
# helper imported by the R1 commit implementation.
STAGE_SERVICE_BASE_OVERLAY_PATHS = tuple(
    path for path in (
        'infrastructure/preselection_pool_store.py',
        'ops/recover_selection_observations.py',
        'ops/run_stage_center_nodes.py',
        'stage_center/end_to_end_deadline.py',
        'stage_center/formula_margin_shadow.py',
        'stage_center/live_collectors.py',
        'stage_center/selection.py',
        'stage_center/hk_stage8/__init__.py',
        'stage_center/hk_stage8/builders.py',
        'stage_center/hk_stage8/precapture.py',
        'stage_center/hk_stage8/rtdata.py',
        'stage_center/hk_stage8/snapshot.py',
        'stage_center/input_contracts.py',
        'stage_center/runner.py',
        'stage_center_tick_config.json',
        'stage_center/consumer.py',
        'ops/run_stage_center_tick.py',
        'domains/preselection.py',
        'domains/task_status.py',
    )
    if path not in STAGE_SERVICE_BASE_PRESERVED_SOURCE_PATHS
)

LEGACY_STAGE_SERVICE_BASE_OVERLAY_PATHS = tuple(
    path for path in (
        'infrastructure/preselection_pool_store.py',
        'ops/recover_selection_observations.py',
        'ops/run_stage_center_nodes.py',
        'stage_center/end_to_end_deadline.py',
        'stage_center/formula_margin_shadow.py',
        'stage_center/live_collectors.py',
        'stage_center/selection.py',
        'stage_center/hk_stage8/__init__.py',
        'stage_center/hk_stage8/builders.py',
        'stage_center/hk_stage8/precapture.py',
        'stage_center/hk_stage8/rtdata.py',
        'stage_center/hk_stage8/snapshot.py',
        'stage_center/input_contracts.py',
        'stage_center/runner.py',
        'stage_center_tick_config.json',
    )
    if path not in STAGE_SERVICE_BASE_PRESERVED_SOURCE_PATHS
)

STAGE_SERVICE_RELEASE_CLOSURE_ROOT_PIN_PATHS = (
    "stage_center/runner.py",
    "domains/task_status.py",
)
STAGE_SERVICE_RELEASE_CLOSURE_ADDED_PATHS = tuple(
    relative for relative in STAGE_SERVICE_RELEASE_CLOSURE_PATHS
    if relative not in STAGE_SERVICE_RELEASE_CLOSURE_ROOT_PIN_PATHS
    and relative not in LEGACY_STAGE_SERVICE_BASE_OVERLAY_PATHS
    and relative not in STAGE_SERVICE_BASE_PRESERVED_SOURCE_PATHS
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
    source_overrides: Mapping[str, Path] | None = None,
) -> None:
    """Require exact source bytes for every selected Stage closure path."""
    selected = set(overlay_paths)
    for relative in STAGE_SERVICE_RELEASE_CLOSURE_PATHS:
        if relative not in selected:
            continue
        if relative in STAGE_SERVICE_BASE_PRESERVED_SOURCE_PATHS:
            # This import-closure path stays supplied by the pinned Stage R4
            # owner because the canonical workspace carries an out-of-scope
            # variant. Its owner bytes are checked from the active inventory.
            expected_owner_sha = STAGE_SERVICE_BASE_PRESERVED_SOURCE_PATHS[relative]
            if STAGE_SERVICE_RELEASE_CLOSURE_SHA256.get(relative) != expected_owner_sha:
                raise ValueError(
                    f"Stage base-preserved closure pin is inconsistent: {relative}"
                )
            continue
        path = (source_overrides or {}).get(relative, source_root / relative)
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


def require_stage_base_preserved_source_hashes(*, app_root: Path) -> list[dict[str, str]]:
    """Verify closure modules intentionally supplied by the pinned owner base."""
    records: list[dict[str, str]] = []
    for relative, expected in sorted(STAGE_SERVICE_BASE_PRESERVED_SOURCE_PATHS.items()):
        path = app_root / relative
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(
                f"Stage base-preserved closure source is missing or unsafe: {relative}"
            )
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(
                f"Stage base-preserved closure source SHA-256 mismatch: {relative}; "
                f"expected {expected}, got {actual}"
            )
        records.append({"path": relative, "sha256": actual})
    return records


def require_complete_strict_stage_overlay(
    *,
    source_root: Path,
    overlay_paths: Sequence[str],
    effective_config: Mapping[str, Any],
    source_overrides: Mapping[str, Path] | None = None,
) -> None:
    """Require the reviewed nine-file cohort when the final config is strict."""
    if effective_config.get("publication_mode") != "strict_commit_required":
        return

    selected = set(overlay_paths)
    required = set(STRICT_STAGE_SERVICE_OVERLAY_PATHS)
    pinned_owner_paths = set(STAGE_SERVICE_BASE_PRESERVED_SOURCE_PATHS)
    missing_selection = sorted(required - selected - pinned_owner_paths)
    if missing_selection:
        raise ValueError(
            "strict Stage overlay requires the complete reviewed or exact owner-preserved cohort; "
            f"missing selected paths: {missing_selection}"
        )
    overrides = source_overrides or {}
    missing_sources = sorted(
        relative for relative in STRICT_STAGE_SERVICE_OVERLAY_PATHS
        if not overrides.get(relative, source_root / relative).is_file()
        or overrides.get(relative, source_root / relative).is_symlink()
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
    manifest_path: Path, manifest_sha256: str, active_config_sha256: str | None = None,
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
        pinned_legacy_pair = (
            identity["release_id"] == PINNED_LEGACY_STAGE_RELEASE_ID
            and active_config["release_id"] == PINNED_LEGACY_STAGE_CONFIG_RELEASE_ID
            and manifest_sha256 == PINNED_LEGACY_STAGE_MANIFEST_SHA256
            and active_config_sha256 == PINNED_LEGACY_STAGE_CONFIG_SHA256
        )
        if not pinned_legacy_pair:
            raise ValueError("Stage active release binding mismatch: config.release_id")
