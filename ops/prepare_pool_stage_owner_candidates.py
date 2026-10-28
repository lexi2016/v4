"""Prepare pinned, inactive R8 API, preselection-scheduler, and Stage candidates.

All outputs are written below the R8 receipt workspace.  This tool never
changes a registered plist, service, data root, or formal release pointer.
"""

from __future__ import annotations

import difflib
import hashlib
import importlib.util
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = Path("/Users/lexi/Desktop/学习/agents调试/V4_POOL_STAGE_HK_IMPLEMENTATION_20261012_R8")
OUTPUT_ROOT = BASE / "candidates" / "r8-pool-stage-20261013-v24"
API_REBASE = BASE / "CURRENT_API_OWNER_REBASE4_R8.json"
CURRENT_API_OWNER_FOR_STAGE_CLIENT_REPAIR = BASE / "CURRENT_API_OWNER_FOR_STAGE_CLIENT_REPAIR_R8.json"
API_STAGE_CLIENT_REBASE_OUTPUT_ROOT = BASE / "candidates" / "r8-api-stage-client-repair-20261013-v1"
API_STAGE_CLIENT_CANDIDATE_ID = "research-workbench-simplification-api-20261013-stage-client-repair-r1"
CURRENT_API_OWNER_RELEASE_ID = "research-workbench-simplification-api-20261013-r8-candidate"
CURRENT_API_OWNER_ROOT = BASE / "candidates" / "r8-pool-stage-20261013-v24" / "api" / CURRENT_API_OWNER_RELEASE_ID
CURRENT_API_OWNER_APP_ROOT = CURRENT_API_OWNER_ROOT / "app"
CURRENT_API_OWNER_MANIFEST = CURRENT_API_OWNER_ROOT / "release-manifest.json"
CURRENT_API_OWNER_MANIFEST_SHA256 = "467a4bc0c6ab9129c974be04b370ec43938f9be47549cffd8a1488209995faf1"
CURRENT_API_OWNER_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
CURRENT_API_OWNER_PLIST_SHA256 = "0c00a20c07630ba20c7c940e8c81b42d3f52c7e137294ce49f2ebd4f9652d7d4"
CURRENT_API_OWNER_BACKUP_PLIST = BASE / "deployment_backups" / "API_V24_BEFORE_STAGE_CLIENT_REPAIR.plist"
PHASE_A_CLIENT_SOURCE_SHA256 = {
    "apps/web/src/api/pool_stage.ts": "42ca7fccb1e5fc83fff5d9c5dcfc82143edc26aae16691c8d2c65e679b8a878e",
    "apps/web/src/api/pool_stage.spec.ts": "98e218f6dfd2edb52a62f0439254e282fdd5e5e51656513929591c3599089d41",
    "apps/web/src/app_shell/types.ts": "dd58d5647376c8890e6d041cc7abc33167b8d4cdb6b77d703c278455552a97d0",
}
CURRENT_API_OWNER_SELECTED_SOURCE_SHA256 = {
    "apps/api/v35_api/app.py": "864cfafd69b1aa6a8245e40b008f84d75dff8f232fc69723494999a98d5c3863",
    "stage_center/consumer.py": "95252cb223a723ee1fea8769cc12d2086bdde1a11d69adcf3502c3c3edd9966a",
    "apps/web/dist/index.html": "75136159e3c9480744c611242b3ac4bd254f70695e6b35ff842311ec5656d6d6",
    "apps/web/dist/assets/main-DMvY0Fqc.js": "77ec2ca7a623f332837722015cc01b5785b3b29d53980aefc1f88a21b4c162eb",
}
FRONTEND_REUSE_ROOT = BASE / "candidates" / "r8-pool-stage-20261013-v20"
RUNTIME_IDENTITY = BASE / "runtime_identity" / "runtime_identity_receipt.json"
STAGE_CALENDAR = BASE / "runtime_identity" / "stage_scheduler_calendar_evidence_r8.json"
DEADLINE_CLOSURE = BASE / "runtime_identity" / "hk_deadline_owner_closure_r8.json"
MODULE_CLOSURE = BASE / "BATCH6B_SCOPE_EXPANSION1_R8.json"
STAGE_PLIST_BACKUP = BASE / "deployment_backups" / "com.lexi.stage-center.scheduler.before.plist"
DEADLINE_PLIST_BACKUP = BASE / "deployment_backups" / "com.lexi.stage-center.hk-deadline.before.plist"
SCHEDULER_PLIST_BACKUP = BASE / "deployment_backups" / "com.lexi.v35.scheduler.before.plist"
SCHEDULER_OWNER_REBASE = BASE / "CURRENT_SCHEDULER_OWNER_REBASE_R8.json"
SCHEDULER_REBASE_OUTPUT_ROOT = BASE / "candidates" / "r8-scheduler-owner-rebase-20261013-v30"
SCHEDULER_REBASE_RELEASE_ID = "research-workbench-simplification-scheduler-20261013-r8-candidate"
SCHEDULER_OWNER_REBASE_SHA256 = "bc99e84b732bafdbc950e1df4a7840a45a1a38e600a6fd863b35c2fbc1e1150b"
SCHEDULER_OWNER_REBASE_MANIFEST_SHA256 = "722df375f7864b4349395f27d3ab4618c7c7fa53b0eb3a8a505bf3abd490b284"
SCHEDULER_OWNER_REBASE_PLIST_SHA256 = "08a51e827561461456ab7795452d3b568ad0a52ca49f182b1b751be73ad770fb"
SCHEDULER_REBASE_SYNC_INPUTS = {
    1: {
        "receipt": BASE / "BATCH1_SYNC_RECEIPT.json",
        "receipt_sha256": "aa1b28d002d4c6bb67ec63079d10862d490c114a291fe1ffd2e84b5ad77067c1",
        "files": BASE / "BATCH1_SYNC_FILES.json",
        "files_sha256": "19df2fa4378a1f7c1dae6efc81e2e593b313b0f58fc6f266d161e360d7cd8024",
    },
    3: {
        "receipt": BASE / "BATCH3_SYNC_RECEIPT.json",
        "receipt_sha256": "7f1c2f9178d99c9692a03b61f5414e1f51b804c19aca99d4919010df97d44972",
        "files": BASE / "BATCH3_SYNC_FILES.json",
        "files_sha256": "6529145fd7dcb29dd5d32b2adf7a76096c88a830f4250c7b3754202ab5766488",
    },
    6: {
        "receipt": BASE / "BATCH6A_SYNC_RECEIPT_R8.json",
        "receipt_sha256": "6d66153880d67f479517adde48aebe3f6f9d17ccf4596b5aa4cd99e072f54713",
        "files": BASE / "BATCH6A_SYNC_FILES_R8.json",
        "files_sha256": "40273393eec22ebf78a974f8193dd3311848c9f4e66d14f2dad7f351807a50a8",
    },
}
SCHEDULER_REBASE_PHASE6B_REVIEW = BASE / "batch6b_review_final" / "PHASE6B_FINAL_REVIEW_RECEIPT_R8.json"
SCHEDULER_REBASE_PHASE6B_REVIEW_SHA256 = "337861dfc000f2a6f09542e28f626ab1ff6abea34cb9b4fbfa935a3ca33ae8d2"
SCHEDULER_REBASE_MODULE_CLOSURE_SHA256 = "5e3563e55464d211e8a1e3c3b3e712576b5014b56302c34704523d81ed30f46a"
SCHEDULER_REBASE_STAGE_OVERLAY_CONTRACT_SHA256 = "26b0420610d11c96805c3d6954c404d4f554a3bb8597ffc3d71c9acfe4b8c68a"
SCHEDULER_REBASE_STAGE_CLOSURE_SUPPORT_SHA256 = {
    "infrastructure/preselection_pool_transactions.py": "22cca047d8d2da3ec9b1c4d3d18fd09026887ee48a95868757bfc598d094d58d",
}
SCHEDULER_REBASE_LOCK_HELPER_SHA256 = {
    "infrastructure/interprocess_lock.py": "9b0cb80a1fe1bcbdebb3936134c8f0bad258c9c9236356022551ff7753351df0",
}
SCHEDULER_REBASE_LOCK_HELPER_OWNER_BEFORE_SHA256 = "5d4cbc01a66bda7eb1b0a3fa96a242c13e9f514a4a525095e8dfd6777dd21fac"
SCHEDULER_REBASE_LOCK_HELPER_SCOPE = BASE / "BATCH6B_SCHEDULER_REBASE_SCOPE_R8.json"
SCHEDULER_REBASE_LOCK_HELPER_SCOPE_SHA256 = "980b53b543839b73c1b13001b35c14da06ee4c1e7dce77744f8cfbba1fb55d8d"
SCHEDULER_REBASE_LOCK_HELPER_IDENTITY = BASE / "SCHEDULER_LOCK_HELPER_DEPENDENCY_IDENTITY_R8.json"
SCHEDULER_REBASE_LOCK_HELPER_IDENTITY_SHA256 = "890fb6c44b5e582dcbc6aea0055cfd96733cdf2c14be26946df1b5664f7ea692"
SCHEDULER_REBASE_LOCK_HELPER_DIFF = BASE / "SCHEDULER_LOCK_HELPER_DEPENDENCY_DIFF_R8.patch"
SCHEDULER_REBASE_LOCK_HELPER_DIFF_SHA256 = "39ff7252bc39c540c28c2c307167690ad0240abd1f3c6904ddac9792c0852f6e"
SCHEDULER_REBASE_IMPORT_CLOSURE_REPORT = BASE / "batch6b_scheduler_rebase_writer" / "missing_import_closure_ast_v3.json"
SCHEDULER_REBASE_IMPORT_CLOSURE_REPORT_SHA256 = "e37feb535ccdf7ddc570a28327885bdfb8544c8bd9e9eb96c0bb6f3982b5fd16"
SCHEDULER_REBASE_MISSING_IMPORT_CLOSURE_SHA256 = {
    "infrastructure/_stage_acquisition_universe_commit_parts/__init__.py": "29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8",
    "infrastructure/_stage_acquisition_universe_commit_parts/_namespace.py": "45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1",
    "infrastructure/_stage_acquisition_universe_contracts_parts/__init__.py": "29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8",
    "infrastructure/_stage_acquisition_universe_contracts_parts/_namespace.py": "45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1",
    "infrastructure/scope_gate.py": "5620d1ee89fbae998d4c801c2a7c4cffac50f890ad0b6951f99230c591dcff68",
    "stage_center/_runner_parts/__init__.py": "29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8",
    "stage_center/_runner_parts/_namespace.py": "45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1",
}
SCHEDULER_REBASE_OWNED_IO_SHA256 = {
    "infrastructure/owned_io.py": "9a74731287ca7c9667643557d4ae42f63453a025665ba28f5b65fdbff7d54ee0",
}
SCHEDULER_REBASE_OWNED_IO_OWNER_BEFORE_SHA256 = "e581daa7b61a9958654802b4c98a0c489b708e632a7e843fe68a513eb0f2e4be"
SCHEDULER_REBASE_OWNED_IO_IDENTITY = BASE / "SCHEDULER_OWNED_IO_DEPENDENCY_IDENTITY_R8.json"
SCHEDULER_REBASE_OWNED_IO_IDENTITY_SHA256 = "10c3ba78e88631e0e66ae7b55920348301c1b95ead891bf1d8dd5b9b1ec75e86"
SCHEDULER_REBASE_OWNED_IO_DIFF = BASE / "SCHEDULER_OWNED_IO_DEPENDENCY_DIFF_R8.patch"
SCHEDULER_REBASE_OWNED_IO_DIFF_SHA256 = "a4c14b965ca0120b4aa04531d110afaa4d926a364e50ea7e95e2ef8d650bafd0"
SCHEDULER_REBASE_PHASE6A_RUNTIME_SHA256 = {
    "domains/_preselection_parts/date_catalog.py": "f816a30e8aa99b3f55f077d884379f36beef5f6f25c1d748ccb8df2a2094622f",
    "infrastructure/preselection_pool_sources.py": "0de0adb98b35fe7210d4026fa9f3fc4af254ac6ea68726e76e6ea357e177f2d7",
    "stage_center/_runner_parts/row_evidence.py": "fd385163fc563d3b4f2c19389fc277e962ee424a0a459c164fbcf8b1669a5b42",
    "stage_center/candidate_input.py": "d35f9db18aedc5ce5e1a62cac9b773b7c227ebf7ecbeacdf53bcb8af8cd315a5",
}
SCHEDULER_REBASE_PHASE6B_RUNTIME_SHA256 = {
    "domains/preselection.py": "85c75d206e5edb66c5dc3f34c8e9d0c1889e73c49950b627fb63c4f12ae9be18",
    "infrastructure/_stage_acquisition_universe_contracts_parts/snapshot_provenance.py": "ddc0250817f92fb5b07998a1e8b82e772551d7e384647f2e5595cb78571bc8e7",
    "infrastructure/_stage_acquisition_universe_contracts_parts/strict_artifact.py": "c7f43ee2cf92bcfc5580c61d7395dd72bf54abc05a8a0e1dfba7fec274d8e439",
    "infrastructure/_stage_acquisition_universe_contracts_parts/snapshot_publication.py": "b863eed25f69e1c2e113968082a8e9e44eb018e398076da82373cb5dc71dba1d",
    "infrastructure/_stage_acquisition_universe_commit_parts/artifact_validation.py": "56a8bd7cb35658865ba92caf445ed3089d05c822f01bf6b86af021580a4e6982",
}
SCHEDULER_REBASE_PRESELECTION_MODULE_SHA256 = {
    "domains/_preselection_parts/__init__.py": "29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8",
    "domains/_preselection_parts/_namespace.py": "45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1",
    "domains/_preselection_parts/date_catalog.py": "f816a30e8aa99b3f55f077d884379f36beef5f6f25c1d748ccb8df2a2094622f",
    "domains/_preselection_parts/independent_projection.py": "0d106ae33b25f7a44e846e7fc1250c0bdb442d08e752b6f8f495edac359d524c",
    "domains/_preselection_parts/pagination_metadata.py": "b1ca5157aa6b6fc082c8a85e25d1132ced381264f3591458b41feb3d27ba3afc",
    "domains/_preselection_parts/pool_assembly.py": "408df356fc7d9806fbb2372fcfd3da6a7afffd05d3e140d9fddc09c347d5ff4e",
    "domains/_preselection_parts/review_fupan.py": "33cd17df2293b94604915dc4e27b4d16fcb97904f403a641b354bc870e06381c",
    "domains/_preselection_parts/review_stage7.py": "86cd191a5212c4986bac45f880b5ef251590863da3802b6523170bc00c24169b",
    "domains/_preselection_parts/source_validation.py": "ba650bb72e78aec6c006faf45804ea670c8fa9c187a45e32b563d31be4605d1d",
}
SCHEDULER_REBASE_CANDIDATE_ADDITION_SHA256 = {
    **SCHEDULER_REBASE_PRESELECTION_MODULE_SHA256,
    **SCHEDULER_REBASE_STAGE_CLOSURE_SUPPORT_SHA256,
    **SCHEDULER_REBASE_LOCK_HELPER_SHA256,
    **SCHEDULER_REBASE_MISSING_IMPORT_CLOSURE_SHA256,
    **SCHEDULER_REBASE_OWNED_IO_SHA256,
}
SCHEDULER_IDENTITY_SCHEDULE_FIELDS = (
    "StartCalendarInterval", "StartInterval", "RunAtLoad", "KeepAlive",
    "WatchPaths", "QueueDirectories", "StartOnMount",
)
SCHEDULER_IDENTITY_EXTERNAL_ROOT_FIELDS = (
    "V35_DATA_ROOT", "V35_PRESELECTION_INPUT_ROOT", "V35_SHARED_DATA_ROOT",
    "V35_STAGE_CENTER_SELECTION_ROOT", "V35_REVIEW_CORE_CLOSE_ROOT",
)
STAGE_BASELINE_APP = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
    "futu-primary-afternoon-20261012-r4/app"
)
SCHEDULER_BASELINE_APP = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
    "research-hourly-empty-20261012-r4/app"
)
API_BASELINE_MANIFEST_SHA = "67353f333429852a135319529b1c786aa1cfdc1b69fb6a464abd0497fe89c290"
API_BACKUP_PLIST_SHA = "a18fefdbcbd3461ef79a60a310dfedb8efcec49f417525f0e98a9e3a9e26d3f2"
SCHEDULER_BASELINE_MANIFEST_SHA = "626c829527f8ec40de324d1a7938e4a26b243516235be806ce273cae0a9b396a"
SCHEDULER_BACKUP_PLIST_SHA = "f0d2dda858a3f53fcf99a6069efd2f67b20087a3c74b68ee0d4a9a78bb315c42"
STAGE_BASELINE_MANIFEST_SHA = "f6d40837d72f17575580bf2c3547d06c42d5cf6af350f2dd9b43be54e1488eda"
STAGE_BACKUP_PLIST_SHA = "e7240c7bde8026e3a4b7a07df0cbdae01e9b5dbcdaabef389bd6fd78ed29063f"
DEADLINE_BACKUP_PLIST_SHA = "3893f19ce08c4f245ff70eb56ccdadcf7e5de08a730d3c7e7b3958a2b360cf22"
SCHEDULER_REUSE_REPORT = BASE / "candidates" / "r8-pool-stage-20261013-v14" / "scheduler" / "scheduler-owner-candidate-report-r8.json"
SCHEDULER_REUSE_MANIFEST_SHA256 = "ff564a2bf2accefc8165bccdab9568c8e45876ae5f1d4270bfe3e0944d68c091"
FRONTEND_MANAGER_SOURCE_SHAS = {
    "src/api/managerStageSelection.ts": "f7854ab5dabc2441a29546a88517e5cf27eb8c90491f750fe02669374654b56a",
    "src/contracts/managerStageSelection.ts": "53893ac1e9b7b1e3cad031d2eb1cdc9d63230d1a011e0969f82ac472eea5df6c",
    "src/views/ManagerSelectionView.vue": "b6be03c9b1011de36014aec889815d35ce4dcc51f9a697653f7f703f9ca5be57",
}
FRONTEND_BUILD_INPUT_FILES = (
    "index.html", "daily-research-command/index.html", "manager-selection/index.html",
    "package.json", "package-lock.json", "tsconfig.json", "vite.config.ts",
)

API_AFTER_SHA256 = {
    "domains/preselection.py": "85c75d206e5edb66c5dc3f34c8e9d0c1889e73c49950b627fb63c4f12ae9be18",
    "infrastructure/preselection_pool_store.py": "7a2a213cecad1ed1cfc96f6c9c0dd18b960fcbd9c932cbe0be444a35952502e1",
    "infrastructure/preselection_pool_readers.py": "7b153abba65eb2387a3f2d87c96466ab5cf38aa331f51b4661940f4c9149c9cc",
    "infrastructure/preselection_pool_sources.py": "0de0adb98b35fe7210d4026fa9f3fc4af254ac6ea68726e76e6ea357e177f2d7",
}
SCHEDULER_BATCH_PATHS = {
    1: (
        "domains/stage_input_producer.py",
        "infrastructure/preselection_pool_store.py",
        "infrastructure/preselection_pool_readers.py",
    ),
    3: (
        "ops/collect_hkconnect_close_snapshot.py",
        "ops/build_close_review.py",
        "domains/close_review.py",
        "infrastructure/review_store.py",
        "infrastructure/hkconnect_close_store.py",
    ),
}
SCHEDULER_REBASE_RUNTIME_OVERLAY_PATHS = (
    *SCHEDULER_BATCH_PATHS[1],
    *SCHEDULER_BATCH_PATHS[3],
    *SCHEDULER_REBASE_PHASE6A_RUNTIME_SHA256,
    *SCHEDULER_REBASE_PHASE6B_RUNTIME_SHA256,
    *SCHEDULER_REBASE_STAGE_CLOSURE_SUPPORT_SHA256,
    *SCHEDULER_REBASE_LOCK_HELPER_SHA256,
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected a regular non-symlink file: {path}")
    return _sha(path.read_bytes())


def _read_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return raw


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _diff(before: bytes, after: bytes, *, before_name: str, after_name: str) -> tuple[bytes, int]:
    left = before.decode("utf-8").splitlines()
    right = after.decode("utf-8").splitlines()
    lines = list(difflib.unified_diff(
        left, right, fromfile=before_name, tofile=after_name, n=0, lineterm=""
    ))
    raw = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    return raw, sum(line.startswith("@@") for line in lines)


def _relative_file(root: Path, relative: str) -> Path:
    path = root / relative
    if path.is_symlink():
        raise ValueError(f"refusing symlink source or owner delta: {relative}")
    return path


def _tree_content_records(root: Path) -> list[dict[str, Any]]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"expected a regular package directory: {root}")
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            records.append({"path": relative, "kind": "symlink", "target": os.readlink(path)})
        elif path.is_file():
            info = path.stat()
            records.append({
                "path": relative,
                "kind": "file",
                "sha256": _file_sha(path),
                "size": info.st_size,
                "mode": f"{stat.S_IMODE(info.st_mode):04o}",
            })
        elif not path.is_dir():
            raise ValueError(f"unsupported shared upstream entry: {path}")
    return records


def _frontend_source_records(web_root: Path) -> list[dict[str, Any]]:
    """Hash the complete isolated V4 source/config graph used for the UI build."""
    records: list[dict[str, Any]] = []
    for relative in [*FRONTEND_BUILD_INPUT_FILES, "src", "public"]:
        path = web_root / relative
        if not path.exists():
            if relative == "public":
                continue
            raise FileNotFoundError(f"canonical frontend build input is missing: {relative}")
        if path.is_symlink():
            raise ValueError(f"canonical frontend source graph contains a symlink: {relative}")
        if path.is_file():
            info = path.stat()
            records.append({
                "path": relative,
                "kind": "file",
                "sha256": _file_sha(path),
                "size": info.st_size,
                "mode": f"{stat.S_IMODE(info.st_mode):04o}",
            })
            continue
        if not path.is_dir():
            raise ValueError(f"canonical frontend build input has an unsupported type: {relative}")
        for child in sorted(path.rglob("*")):
            child_relative = child.relative_to(web_root).as_posix()
            if child.is_symlink():
                raise ValueError(f"canonical frontend source graph contains a symlink: {child_relative}")
            if child.is_dir():
                continue
            if not child.is_file():
                raise ValueError(f"canonical frontend source graph contains a non-file: {child_relative}")
            info = child.stat()
            records.append({
                "path": child_relative,
                "kind": "file",
                "sha256": _file_sha(child),
                "size": info.st_size,
                "mode": f"{stat.S_IMODE(info.st_mode):04o}",
            })
    return sorted(records, key=lambda row: str(row["path"]))


def _compile_canonical_frontend(
    root: Path,
    candidate_app: Path,
    api_release: Any,
    *,
    purpose: str = "b4",
    required_source_shas: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Compile the current full canonical source graph to candidate-owned dist bytes."""
    if not re.fullmatch(r"[a-z0-9-]+", purpose):
        raise ValueError("canonical frontend build purpose is not a safe path token")
    source_web = REPO_ROOT / "apps/web"
    source_records = _frontend_source_records(source_web)
    source_by_path = {str(row["path"]): row for row in source_records}
    for relative, expected_sha in FRONTEND_MANAGER_SOURCE_SHAS.items():
        row = source_by_path.get(relative)
        if row is None or row.get("sha256") != expected_sha:
            raise ValueError(f"current Manager peer frontend source drifted: {relative}")
    for relative, expected_sha in (required_source_shas or {}).items():
        source_relative = relative.removeprefix("apps/web/")
        if source_relative == relative and "/" in relative:
            raise ValueError(f"required canonical frontend path is outside apps/web: {relative}")
        row = source_by_path.get(source_relative)
        if row is None or row.get("sha256") != expected_sha:
            raise ValueError(f"required canonical frontend source differs from its approved SHA: {relative}")

    source_root = root / "frontend-source"
    staged_web = source_root / "apps" / "web"
    staged_web.parent.mkdir(parents=True, exist_ok=True)
    for relative in FRONTEND_BUILD_INPUT_FILES:
        source = source_web / relative
        target = staged_web / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for directory in ("src", "public"):
        source = source_web / directory
        if source.is_dir():
            shutil.copytree(source, staged_web / directory, symlinks=False)
    staged_source_records = _frontend_source_records(staged_web)
    if staged_source_records != source_records:
        raise ValueError("isolated canonical frontend source copy differs from its frozen input graph")

    dependency_root = source_web / "node_modules"
    if dependency_root.is_symlink() or not dependency_root.is_dir():
        raise ValueError("canonical frontend installed dependency root is missing or unsafe")
    (staged_web / "node_modules").symlink_to(dependency_root, target_is_directory=True)
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        raise RuntimeError("canonical frontend build requires the observed Node and npm executables")
    node_version = subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    npm_version = subprocess.run([npm, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    dependency_lock = dependency_root / ".package-lock.json"
    if not dependency_lock.is_file() or dependency_lock.is_symlink():
        raise ValueError("installed frontend dependency lock metadata is missing or unsafe")
    installed_lock = _read_json(dependency_lock)
    installed_package_records = installed_lock.get("packages")
    if not isinstance(installed_package_records, dict):
        raise ValueError("installed frontend dependency lock metadata has no package graph")
    installed_lock_sha_before = _file_sha(dependency_lock)
    installed_package_graph_sha_before = _sha(json.dumps(
        installed_package_records, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8"))
    manager_versions = {}
    for module in ("vite", "vitest", "vue", "vue-tsc", "@vitejs/plugin-vue", "@testing-library/vue"):
        metadata = _read_json(dependency_root / module / "package.json")
        manager_versions[module] = {
            "version": metadata.get("version"),
            "package_json_sha256": _file_sha(dependency_root / module / "package.json"),
        }

    build_output_root = root / "frontend-build-output"
    build_dist = build_output_root / "apps/web/dist"
    if build_output_root.exists() or build_output_root.is_symlink():
        raise FileExistsError("refusing to overwrite the isolated frontend build output")
    build_dist.parent.mkdir(parents=True, exist_ok=True)
    command = [npm, "run", "build", "--", "--outDir", str(build_dist)]
    env = dict(os.environ)
    env.update({
        "CI": "true",
        "NODE_ENV": "production",
        "npm_config_update_notifier": "false",
        "npm_config_audit": "false",
        "npm_config_fund": "false",
    })
    completed = subprocess.run(command, cwd=staged_web, env=env, capture_output=True, text=True)
    log_path = root / "logs" / f"canonical-{purpose}-frontend-build.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_text = (
        "command=" + json.dumps(command, ensure_ascii=False) + "\n"
        + "cwd=" + str(staged_web) + "\n"
        + "exit_code=" + str(completed.returncode) + "\n"
        + "--- stdout ---\n" + completed.stdout
        + "\n--- stderr ---\n" + completed.stderr
    )
    with log_path.open("x", encoding="utf-8") as handle:
        handle.write(log_text)
    if completed.returncode != 0:
        raise RuntimeError(f"isolated canonical frontend build failed; see {log_path}")
    if not (build_dist / "index.html").is_file():
        raise ValueError("isolated canonical frontend build did not emit an index.html")
    fresh_dist_inventory = [
        row for row in api_release.inventory_tree(build_output_root)
        if str(row["path"]) == "apps/web/dist" or str(row["path"]).startswith("apps/web/dist/")
    ]
    if not fresh_dist_inventory:
        raise ValueError("isolated canonical frontend build emitted an empty distribution")
    if any(row.get("kind") != "file" for row in fresh_dist_inventory):
        raise ValueError("isolated canonical frontend build emitted a non-file distribution entry")
    candidate_dist = candidate_app / "apps/web/dist"
    candidate_dist.parent.mkdir(parents=True, exist_ok=True)
    for row in fresh_dist_inventory:
        relative = str(row["path"])
        source = api_release._safe_child(build_output_root, relative, allow_missing=False)
        target = api_release._safe_child(candidate_app, relative, allow_missing=True)
        if source.is_symlink() or not source.is_file() or target.is_symlink():
            raise ValueError(f"canonical frontend emitted an unsafe dist entry: {relative}")
        if target.exists():
            if not target.is_file():
                raise ValueError(f"current API owner dist target is not a file: {relative}")
            target.chmod(stat.S_IMODE(target.stat().st_mode) | stat.S_IWUSR)
            shutil.copy2(source, target)
        else:
            with api_release._candidate_parent_writable(candidate_app, relative) as writable_target:
                shutil.copy2(source, writable_target)
        if (_file_sha(target) != row.get("sha256")
                or target.stat().st_size != row.get("size")
                or f"{stat.S_IMODE(target.stat().st_mode):04o}" != row.get("mode")):
            raise ValueError(f"fresh canonical frontend dist entry differs after candidate install: {relative}")
    dist_inventory = [
        row for row in api_release.inventory_tree(candidate_app)
        if str(row["path"]) == "apps/web/dist" or str(row["path"]).startswith("apps/web/dist/")
    ]
    if not dist_inventory:
        raise ValueError("candidate API owner dist is missing after fresh frontend build")
    source_copy_after = _frontend_source_records(staged_web)
    if source_copy_after != source_records:
        raise ValueError("frontend source graph changed during isolated compilation")
    installed_lock_sha_after = _file_sha(dependency_lock)
    installed_lock_after = _read_json(dependency_lock)
    installed_package_records_after = installed_lock_after.get("packages")
    if not isinstance(installed_package_records_after, dict):
        raise ValueError("installed frontend dependency package graph disappeared during compilation")
    installed_package_graph_sha_after = _sha(json.dumps(
        installed_package_records_after, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8"))
    manager_versions_after = {}
    for module in manager_versions:
        metadata_path = dependency_root / module / "package.json"
        metadata = _read_json(metadata_path)
        manager_versions_after[module] = {
            "version": metadata.get("version"),
            "package_json_sha256": _file_sha(metadata_path),
        }
    if (
        installed_lock_sha_after != installed_lock_sha_before
        or installed_package_graph_sha_after != installed_package_graph_sha_before
        or manager_versions_after != manager_versions
    ):
        raise ValueError("installed frontend dependency metadata changed during isolated compilation")
    input_aggregate = _sha(json.dumps(source_records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    receipt = {
        "schema_version": "r8.canonical_frontend_build.v1",
        "build_purpose": purpose,
        "status": "BUILT_CANDIDATE_ONLY",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "source_root": str(source_web),
        "isolated_source_root": str(staged_web),
        "source_graph_sha256": input_aggregate,
        "source_input_entry_count": len(source_records),
        "source_inputs": source_records,
        "manager_peer_sources_exact": {
            path: source_by_path[path]["sha256"] for path in FRONTEND_MANAGER_SOURCE_SHAS
        },
        "package_json_sha256": source_by_path["package.json"]["sha256"],
        "package_lock_sha256": source_by_path["package-lock.json"]["sha256"],
        "installed_dependency_lock_sha256": _file_sha(dependency_lock),
        "installed_dependency_lock_unchanged_during_build": True,
        "installed_dependency_package_graph_sha256": _sha(json.dumps(installed_package_records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")),
        "installed_dependency_package_graph_unchanged_during_build": True,
        "installed_dependency_package_count": len(installed_package_records),
        "verified_build_tool_versions": manager_versions,
        "node_version": node_version,
        "npm_version": npm_version,
        "build_command": command,
        "build_working_directory": str(staged_web),
        "build_log_path": str(log_path),
        "build_log_sha256": _file_sha(log_path),
        "candidate_dist_root": str(candidate_dist),
        "candidate_dist_inventory": dist_inventory,
        "candidate_dist_inventory_sha256": api_release.inventory_digest(dist_inventory),
        "fresh_build_dist_root": str(build_dist),
        "fresh_build_dist_inventory": fresh_dist_inventory,
        "fresh_build_dist_inventory_sha256": api_release.inventory_digest(fresh_dist_inventory),
        "fresh_build_emitted_dist_paths": [str(row["path"]) for row in fresh_dist_inventory],
        "owner_dist_entries_preserved_when_not_replaced": True,
        "current_workspace_dist_copied": False,
        "canonical_dist_written": False,
        "candidate_only_dist_write": True,
        "active_owner_dist_entries_preserved_when_not_replaced": True,
    }
    receipt_path = root / "api" / f"canonical-{purpose}-frontend-build-r8.json"
    _write_json(receipt_path, receipt)
    receipt["receipt_path"] = str(receipt_path)
    receipt["receipt_sha256"] = _file_sha(receipt_path)
    return receipt


def _register_generated_frontend_api_delta(
    *, root: Path, api_candidate_root: Path, active_app: Path, candidate_app: Path,
    api_release: Any, integration: dict[str, Any], frontend_build: dict[str, Any],
    source_category: str = "GENERATED_CANONICAL_B4_FRONTEND_BUILD",
) -> dict[str, Any]:
    """Add only newly compiled dist changes to the existing candidate delta receipt."""
    delta_path = root / "api" / "api-integration-delta-r8.json"
    receipt = _read_json(delta_path)
    entries = list(receipt.get("entries", []))
    existing_paths = {str(row.get("path")) for row in entries if isinstance(row, dict)}
    dist_rows = list(frontend_build.get("candidate_dist_inventory", []))
    generated_entries: list[dict[str, Any]] = []
    for row in dist_rows:
        relative = str(row["path"])
        if not relative.startswith("apps/web/dist/"):
            continue
        if relative in existing_paths:
            raise ValueError("frontend dist unexpectedly overlaps an existing source delta path")
        owner_path = active_app / relative
        candidate_path = candidate_app / relative
        if owner_path.is_symlink() or candidate_path.is_symlink() or not candidate_path.is_file():
            raise ValueError(f"generated frontend API delta path is unsafe: {relative}")
        before_raw = owner_path.read_bytes() if owner_path.exists() else None
        after_raw = candidate_path.read_bytes()
        before_sha = _sha(before_raw) if before_raw is not None else None
        after_sha = _sha(after_raw)
        if before_sha == after_sha:
            continue
        if before_raw is None:
            diff_sha = None
            hunk_count = None
        else:
            diff_sha, hunk_count = api_release._diff_proof(before_raw, after_raw)
            if diff_sha is None or hunk_count is None:
                raise ValueError(f"generated frontend changed a non-text owner dist path: {relative}")
        generated_entries.append({
            "path": relative,
            "before_sha256": before_sha,
            "after_sha256": after_sha,
            "unified_diff_sha256": diff_sha,
            "unified_diff_hunk_count": hunk_count,
        })
    entries.extend(generated_entries)
    entries.sort(key=lambda row: str(row["path"]))
    source_categories = receipt.get("source_categories")
    if not isinstance(source_categories, dict):
        raise ValueError("API delta receipt source categories are invalid")
    for row in generated_entries:
        source_categories[row["path"]] = source_category
    receipt["entries"] = entries
    receipt["candidate_generated_frontend_assets"] = {
        "classification": "GENERATED_CANDIDATE_DIST_DELTA",
        "source_graph_sha256": frontend_build["source_graph_sha256"],
        "candidate_dist_inventory_sha256": frontend_build["candidate_dist_inventory_sha256"],
        "changed_or_added_entries": generated_entries,
    }
    candidate_receipt_path = api_candidate_root / api_release.DELTA_RECEIPT_NAME
    if candidate_receipt_path.is_symlink() or not candidate_receipt_path.is_file():
        raise ValueError("API candidate delta receipt copy is missing or unsafe")
    canonical_json = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    delta_path.write_text(canonical_json, encoding="utf-8")
    candidate_receipt_path.write_text(canonical_json, encoding="utf-8")
    records, preserved = api_release._verify_delta_files(
        base_app=active_app,
        candidate_app=candidate_app,
        entries=api_release._validate_delta_receipt(receipt, base_identity=integration["base"]),
    )
    receipt_sha = _sha(canonical_json.encode("utf-8"))
    integration["delta_receipt_sha256"] = receipt_sha
    integration["delta_entries"] = records
    integration["non_delta_active_release_bytes_preserved"] = True
    integration["non_delta_entry_count"] = len(preserved)
    integration["non_delta_inventory_sha256"] = api_release.inventory_digest(preserved)
    integration["active_application_inventory_sha256"] = api_release.inventory_digest(api_release.inventory_tree(active_app))
    integration["candidate_generated_frontend_assets"] = receipt["candidate_generated_frontend_assets"]
    return {
        "path": str(delta_path),
        "candidate_copy_path": str(candidate_receipt_path),
        "sha256": receipt_sha,
        "generated_delta_count": len(generated_entries),
        "generated_delta_paths": [row["path"] for row in generated_entries],
        "all_frontend_changes_bound_by_existing_api_delta_verifier": True,
    }


def _reuse_canonical_frontend(root: Path, candidate_app: Path, api_release: Any) -> dict[str, Any]:
    """Reuse the verified v20 canonical build outputs on a freshly copied API owner base."""
    reuse_candidates_path = FRONTEND_REUSE_ROOT / "OWNER_CANDIDATES_R8.json"
    prior = _read_json(reuse_candidates_path)
    if (prior.get("candidate_status") != "READY_FOR_INDEPENDENT_REVIEW"
            or prior.get("activation_status") != "NOT_ACTIVATED"):
        raise ValueError("reusable Stage/frontend candidate receipt is not ready or was activated")

    # Reuse only the already-passing Stage and scheduler candidate artifacts when their
    # receipts and actual packaged inventories still match the immutable v20 manifests.
    stage = prior.get("stage")
    scheduler = prior.get("scheduler")
    if not isinstance(stage, dict) or not isinstance(scheduler, dict):
        raise ValueError("v20 owner candidate receipt is missing Stage or scheduler references")
    stage_report_path = Path(str(stage.get("report_path", "")))
    scheduler_report_path = Path(str(scheduler.get("report_path", "")))
    if stage_report_path.is_symlink() or scheduler_report_path.is_symlink():
        raise ValueError("v20 reusable Stage/scheduler report is a symlink")
    stage_report = _read_json(stage_report_path)
    scheduler_report = _read_json(scheduler_report_path)
    if stage_report != stage.get("report") or scheduler_report != scheduler.get("report"):
        raise ValueError("v20 reusable Stage/scheduler reports differ from their aggregate receipt")

    stage_manifest_path = Path(str(stage_report.get("manifest_path", "")))
    stage_candidate_root = Path(str(stage_report.get("candidate_root", "")))
    stage_candidate_app = stage_candidate_root / "app"
    if stage_manifest_path.is_symlink() or stage_candidate_app.is_symlink():
        raise ValueError("v20 reusable Stage candidate manifest/app is a symlink")
    stage_manifest_raw = stage_manifest_path.read_bytes()
    stage_manifest = json.loads(stage_manifest_raw)
    stage_manifest_sha = _sha(stage_manifest_raw)
    if stage_manifest_sha != stage_report.get("candidate_manifest_sha256"):
        raise ValueError("v20 Stage candidate manifest SHA changed after its canary")
    if api_release.inventory_tree(stage_candidate_app) != stage_manifest["application_inventory"]["entries"]:
        raise ValueError("v20 Stage candidate inventory changed after its canary")
    if not (
        stage_report.get("deadline_calendar_preserved") is True
        and stage_report.get("deadline_run_at_load_false") is True
        and stage_report.get("deadline_only_flag_preserved") is True
    ):
        raise ValueError("v20 Stage candidate deadline-only calendar proof is incomplete")

    scheduler_manifest_path = Path(str(scheduler_report.get("candidate_manifest", "")))
    if scheduler_manifest_path.is_symlink():
        raise ValueError("v20 scheduler candidate manifest is a symlink")
    scheduler_manifest_raw = scheduler_manifest_path.read_bytes()
    scheduler_manifest = json.loads(scheduler_manifest_raw)
    scheduler_manifest_sha = _sha(scheduler_manifest_raw)
    scheduler_app = Path(str(scheduler_manifest["candidate"]["app_root"]))
    if scheduler_manifest_sha != scheduler_report.get("candidate_manifest_sha256"):
        raise ValueError("v20 reused scheduler manifest SHA no longer matches its report")
    if api_release.inventory_tree(scheduler_app) != scheduler_manifest["application_inventory"]["entries"]:
        raise ValueError("v20 reused scheduler candidate inventory changed")
    scheduler_roots = scheduler_report.get("roots_preserved")
    scheduler_fields = scheduler_report.get("schedule_fields_preserved")
    scheduler_staged_plist_record = scheduler_report.get("staged_plist")
    if not isinstance(scheduler_staged_plist_record, dict):
        raise ValueError("v20 reused scheduler staged plist record is invalid")
    scheduler_staged_plist_path = Path(str(scheduler_staged_plist_record.get("path", "")))
    if scheduler_staged_plist_path.is_symlink():
        raise ValueError("v20 reused scheduler staged plist is a symlink")
    scheduler_owner_plist_raw = SCHEDULER_PLIST_BACKUP.read_bytes()
    scheduler_staged_plist_raw = scheduler_staged_plist_path.read_bytes()
    scheduler_owner_plist = plistlib.loads(scheduler_owner_plist_raw)
    scheduler_staged_plist = plistlib.loads(scheduler_staged_plist_raw)
    owner_environment = scheduler_owner_plist.get("EnvironmentVariables", {})
    staged_environment = scheduler_staged_plist.get("EnvironmentVariables", {})
    if (_sha(scheduler_owner_plist_raw) != SCHEDULER_BACKUP_PLIST_SHA
            or _sha(scheduler_staged_plist_raw) != scheduler_staged_plist_record.get("sha256")
            or not isinstance(scheduler_roots, dict) or not scheduler_roots
            or not isinstance(scheduler_fields, dict)
            or scheduler_report.get("calendar_slots_preserved") is not True
            or scheduler_report.get("run_at_load_preserved") is not True
            or scheduler_report.get("non_delta_owner_bytes_preserved") is not True
            or any(owner_environment.get(key) != value or staged_environment.get(key) != value
                   for key, value in scheduler_roots.items())
            or any(scheduler_owner_plist.get(key) != scheduler_staged_plist.get(key)
                   or scheduler_fields.get(key) != scheduler_staged_plist.get(key)
                   for key in ("KeepAlive", "QueueDirectories", "RunAtLoad", "StartCalendarInterval", "StartInterval", "StartOnMount", "WatchPaths"))):
        raise ValueError("v20 reused scheduler identity/calendar proof is incomplete")

    previous_frontend = prior.get("api", {}).get("report", {}).get("frontend_assets", {}).get("canonical_build_receipt")
    if not isinstance(previous_frontend, dict):
        raise ValueError("v20 candidate is missing its canonical frontend build receipt")
    previous_receipt_path = Path(str(previous_frontend.get("receipt_path", "")))
    if previous_receipt_path.is_symlink():
        raise ValueError("v20 canonical frontend receipt is a symlink")
    previous_receipt_raw = previous_receipt_path.read_bytes()
    if _sha(previous_receipt_raw) != previous_frontend.get("receipt_sha256"):
        raise ValueError("v20 canonical frontend build receipt changed")
    previous_receipt = json.loads(previous_receipt_raw)
    source_web = REPO_ROOT / "apps/web"
    source_records = _frontend_source_records(source_web)
    source_by_path = {str(row["path"]): row for row in source_records}
    if previous_receipt.get("source_inputs") != source_records:
        raise ValueError("canonical B4 source graph changed since the passing v20 frontend build")
    for relative, expected_sha in FRONTEND_MANAGER_SOURCE_SHAS.items():
        if source_by_path.get(relative, {}).get("sha256") != expected_sha:
            raise ValueError(f"current Manager peer frontend source drifted: {relative}")

    isolated_source = Path(str(previous_receipt.get("isolated_source_root", "")))
    if isolated_source.is_symlink() or _frontend_source_records(isolated_source) != source_records:
        raise ValueError("v20 isolated canonical frontend source snapshot changed")
    dependency_root = source_web / "node_modules"
    dependency_lock = dependency_root / ".package-lock.json"
    if _file_sha(dependency_lock) != previous_receipt.get("installed_dependency_lock_sha256"):
        raise ValueError("installed frontend dependency lock changed since the v20 build")
    for module, expected in previous_receipt.get("verified_build_tool_versions", {}).items():
        metadata_path = dependency_root / module / "package.json"
        metadata = _read_json(metadata_path)
        if (metadata.get("version") != expected.get("version")
                or _file_sha(metadata_path) != expected.get("package_json_sha256")):
            raise ValueError(f"installed frontend build tool changed since v20: {module}")

    prior_build_log = Path(str(previous_receipt.get("build_log_path", "")))
    if prior_build_log.is_symlink() or _file_sha(prior_build_log) != previous_receipt.get("build_log_sha256"):
        raise ValueError("v20 isolated frontend build log changed")
    v20_dist_root = Path(str(previous_receipt.get("candidate_dist_root", "")))
    v20_candidate_app = v20_dist_root.parents[2]
    v20_actual_dist = [
        row for row in api_release.inventory_tree(v20_candidate_app)
        if row["path"] == "apps/web/dist" or row["path"].startswith("apps/web/dist/")
    ]
    if v20_actual_dist != previous_receipt.get("candidate_dist_inventory"):
        raise ValueError("v20 canonical frontend candidate dist inventory changed")
    receipt_rows = {
        str(row["path"]): row for row in previous_receipt["candidate_dist_inventory"]
        if str(row.get("path", "")).startswith("apps/web/dist/")
    }
    emitted_paths: list[str] = []
    build_log_text = prior_build_log.read_text(encoding="utf-8")
    marker = "/apps/web/dist/"
    for line in build_log_text.splitlines():
        if marker not in line or " kB" not in line:
            continue
        relative = line.split(marker, 1)[1].split()[0]
        normalized = Path(relative).as_posix()
        if normalized in emitted_paths:
            continue
        emitted_paths.append(normalized)
    expected_entries = {
        "index.html", "daily-research-command/index.html", "manager-selection/index.html",
    }
    if not expected_entries.issubset(set(emitted_paths)) or not emitted_paths:
        raise ValueError("v20 Vite build log does not prove all canonical frontend entrypoints")

    destination_dist = candidate_app / "apps/web/dist"
    for relative in emitted_paths:
        app_relative = "apps/web/dist/" + relative
        normalized = Path(app_relative).as_posix()
        if normalized != app_relative or app_relative not in receipt_rows:
            raise ValueError(f"v20 emitted frontend path is not manifest-bound: {relative}")
        source = v20_dist_root / relative
        target = api_release._safe_child(candidate_app, app_relative, allow_missing=True)
        expected_row = receipt_rows[app_relative]
        if (source.is_symlink() or not source.is_file()
                or _file_sha(source) != expected_row.get("sha256")
                or source.stat().st_size != expected_row.get("size")):
            raise ValueError(f"v20 emitted frontend file differs from its manifest: {relative}")
        if target.is_symlink():
            raise ValueError(f"current API candidate frontend target is unsafe: {app_relative}")
        if target.exists():
            if not target.is_file():
                raise ValueError(f"current API candidate frontend target is not a file: {app_relative}")
            target.chmod(stat.S_IMODE(target.stat().st_mode) | stat.S_IWUSR)
            shutil.copy2(source, target)
        else:
            with api_release._candidate_parent_writable(candidate_app, app_relative) as writable_target:
                shutil.copy2(source, writable_target)
        if (_file_sha(target) != expected_row.get("sha256")
                or target.stat().st_size != expected_row.get("size")):
            raise ValueError(f"reused canonical frontend file differs after owner rebase: {relative}")

    candidate_dist = candidate_app / "apps/web/dist"
    candidate_dist_inventory = [
        row for row in api_release.inventory_tree(candidate_app)
        if row["path"] == "apps/web/dist" or row["path"].startswith("apps/web/dist/")
    ]
    receipt = dict(previous_receipt)
    receipt.pop("api_integration_generated_delta", None)
    receipt.update({
        "candidate_dist_root": str(candidate_dist),
        "candidate_dist_inventory": candidate_dist_inventory,
        "candidate_dist_inventory_sha256": api_release.inventory_digest(candidate_dist_inventory),
        "reused_from_frontend_candidate_root": str(FRONTEND_REUSE_ROOT),
        "reused_from_frontend_receipt_path": str(previous_receipt_path),
        "reused_from_frontend_receipt_sha256": previous_frontend["receipt_sha256"],
        "reused_stage_candidate_manifest_sha256": stage_manifest_sha,
        "reused_scheduler_candidate_manifest_sha256": scheduler_manifest_sha,
        "fresh_vite_emitted_dist_paths": sorted(emitted_paths),
        "owner_dist_bytes_preserved_except_fresh_vite_emitted_paths": True,
        "active_r4_dist_entries_preserved_when_not_replaced": True,
        "frontend_build_reused_without_recompilation": True,
    })
    receipt_path = root / "api" / "canonical-b4-frontend-build-r8.json"
    _write_json(receipt_path, receipt)
    receipt["receipt_path"] = str(receipt_path)
    receipt["receipt_sha256"] = _file_sha(receipt_path)
    return receipt


def _verify_stage_config_identity_render(
    *,
    candidate_root: Path,
    candidate_app: Path,
    stage_manifest: Mapping[str, Any],
    service_binding: Mapping[str, Any],
    stage_overlay_paths: list[str],
) -> dict[str, Any]:
    """Verify the exact, two-field identity render authorized for Stage config."""
    relative = "stage_center_tick_config.json"
    rule_path = BASE / "BATCH6B_GENERATED_STAGE_CONFIG_RENDER_R8.json"
    rule = _read_json(rule_path)
    if (rule.get("schema_version") != "r8.batch6b.generated_stage_config_identity_render.v1"
            or rule.get("path") != relative
            or rule.get("owner_sha256") != "437b1db3b4ac9f38e6c0e28ad002fa2d22bfcbaba139f4d2290ce35eb898ed54"
            or rule.get("source_mode") != "EXACT_OWNER_SOURCE_NO_CANONICAL_OVERLAY"
            or rule.get("candidate_mode") != "GENERATED_IDENTITY_RENDER"):
        raise ValueError("Stage config identity-render ruling does not match the pinned scope")
    allowed_fields = set(rule.get("allowed_changed_json_fields", []))
    if allowed_fields != {"release_id", "shared_data_root"}:
        raise ValueError("Stage config identity-render allowed-field set changed")

    owner_config_path = STAGE_BASELINE_APP / relative
    frozen_config_path = BASE / "candidate_source_closure_frozen_owner" / relative
    canonical_config_path = REPO_ROOT / relative
    candidate_config_path = candidate_app / relative
    owner_raw = owner_config_path.read_bytes()
    frozen_raw = frozen_config_path.read_bytes()
    candidate_raw = candidate_config_path.read_bytes()
    owner_sha = _sha(owner_raw)
    frozen_sha = _sha(frozen_raw)
    candidate_sha = _sha(candidate_raw)
    if owner_sha != frozen_sha or owner_sha != rule["owner_sha256"]:
        raise ValueError("Stage config owner and frozen identity-render source differ")
    if relative in stage_overlay_paths:
        raise ValueError("Stage config identity render must not be a source overlay")

    owner_json = json.loads(owner_raw.decode("utf-8"))
    frozen_json = json.loads(frozen_raw.decode("utf-8"))
    candidate_json = json.loads(candidate_raw.decode("utf-8"))
    if not all(isinstance(item, dict) for item in (owner_json, frozen_json, candidate_json)):
        raise ValueError("Stage config identity-render inputs must be JSON objects")
    if owner_json != frozen_json:
        raise ValueError("Stage config frozen JSON content differs from the exact owner")
    changed_fields = sorted(
        key for key in (set(owner_json) | set(candidate_json))
        if owner_json.get(key) != candidate_json.get(key)
    )
    if set(changed_fields) != allowed_fields:
        raise ValueError(
            "Stage config identity render changed fields outside the exact ruling: "
            f"{changed_fields}"
        )
    for key in set(owner_json) | set(candidate_json):
        if key not in allowed_fields and owner_json.get(key) != candidate_json.get(key):
            raise ValueError(f"Stage config identity render changed protected field: {key}")

    candidate_release_id = str(stage_manifest.get("candidate", {}).get("release_id", ""))
    if not candidate_release_id or candidate_json.get("release_id") != candidate_release_id:
        raise ValueError("Stage config release_id does not match the candidate manifest")
    expected_shared_root = candidate_app / "upstreams" / "v3_shared_data"
    candidate_shared_root = Path(str(candidate_json.get("shared_data_root", "")))
    owner_shared_root = Path(str(owner_json.get("shared_data_root", "")))
    stage_r4_shared_root = STAGE_BASELINE_APP / "upstreams" / "v3_shared_data"
    if (candidate_shared_root.resolve() != expected_shared_root.resolve()
            or not owner_shared_root.is_absolute()
            or not owner_shared_root.is_dir()):
        raise ValueError("Stage shared_data_root identity render changed the packaged upstream source")
    owner_package_records = _tree_content_records(owner_shared_root)
    stage_r4_package_records = _tree_content_records(stage_r4_shared_root)
    candidate_package_records = _tree_content_records(candidate_shared_root)
    if (owner_package_records != stage_r4_package_records
            or owner_package_records != candidate_package_records):
        raise ValueError("Stage candidate packaged shared-data upstream bytes differ from the R4 owner")
    package_digest = _sha(json.dumps(
        owner_package_records, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8"))

    loader_path = candidate_app / "infrastructure" / "isolated_package_loader.py"
    owner_loader_path = STAGE_BASELINE_APP / "infrastructure" / "isolated_package_loader.py"
    if _file_sha(loader_path) != _file_sha(owner_loader_path):
        raise ValueError("Stage candidate isolated shared-package loader differs from R4 owner bytes")
    spec = importlib.util.spec_from_file_location("_r8_candidate_isolated_package_loader", loader_path)
    if spec is None or spec.loader is None:
        raise ValueError("Stage candidate isolated package loader cannot be imported")
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    shared_module = loader.load_isolated_package_module(
        candidate_shared_root,
        package_directory="shared_data",
        module_leaf="public_fupan",
        namespace_prefix="r8stagecandidate_shared_data",
    )
    module_origin = Path(str(shared_module.__file__)).resolve()
    if not module_origin.is_relative_to(candidate_shared_root.resolve()):
        raise ValueError("Stage shared-data module did not load from the candidate package root")
    namespace_prefix = str(shared_module.__package__).rsplit(".", 1)[0]
    loaded_package_modules = {
        name: str(module.__file__)
        for name, module in sorted(sys.modules.items())
        if name == namespace_prefix or name.startswith(namespace_prefix + ".")
        if getattr(module, "__file__", None)
    }
    if not loaded_package_modules or any(
        not Path(path).resolve().is_relative_to(candidate_shared_root.resolve())
        for path in loaded_package_modules.values()
    ):
        raise ValueError("Stage shared-data import contains a module outside the candidate package root")

    stage_manifest_path = candidate_root / "release-manifest.json"
    manifest_sha = _file_sha(stage_manifest_path)
    inventory_rows = stage_manifest.get("application_inventory", {}).get("entries", [])
    config_inventory_rows = [row for row in inventory_rows if row.get("path") == relative]
    if len(config_inventory_rows) != 1 or config_inventory_rows[0].get("sha256") != candidate_sha:
        raise ValueError("Stage config after-SHA is not pinned by the candidate app inventory")
    plist_path = Path(str(service_binding.get("path", "")))
    plist_payload = plistlib.loads(plist_path.read_bytes())
    plist_env = plist_payload.get("EnvironmentVariables", {})
    arguments = plist_payload.get("ProgramArguments", [])
    if (plist_env.get("V35_RELEASE_ID") != candidate_release_id
            or plist_env.get("V35_RELEASE_MANIFEST_SHA256") != manifest_sha
            or Path(str(arguments[4])).resolve() != candidate_config_path.resolve()):
        raise ValueError("Stage rendered service plist does not bind the candidate config and manifest")

    diff_raw, diff_hunks = _diff(
        owner_raw,
        candidate_raw,
        before_name=f"stage-r4-owner/{relative}",
        after_name=f"candidate/{relative}",
    )
    diff_path = candidate_root.parent / "stage-config-identity-render-r8.diff"
    with diff_path.open("xb") as handle:
        handle.write(diff_raw)
    receipt = {
        "schema_version": "r8.stage.generated_config_identity_render.v1",
        "ruling_path": str(rule_path),
        "ruling_sha256": _file_sha(rule_path),
        "prior_conflict_evidence_path": str(BASE / "batch6b_writer" / "STAGE_CONFIG_IDENTITY_DIFF_R8.json"),
        "prior_conflict_evidence_sha256": _file_sha(BASE / "batch6b_writer" / "STAGE_CONFIG_IDENTITY_DIFF_R8.json"),
        "path": relative,
        "classification": "GENERATED_IDENTITY_RENDER",
        "source_mode": "EXACT_OWNER_SOURCE_NO_CANONICAL_OVERLAY",
        "candidate_mode": "GENERATED_IDENTITY_RENDER",
        "owner_source_path": str(owner_config_path),
        "frozen_source_path": str(frozen_config_path),
        "canonical_source_sha256_read_only": _file_sha(canonical_config_path),
        "owner_sha256": owner_sha,
        "frozen_owner_snapshot_sha256": frozen_sha,
        "candidate_after_sha256": candidate_sha,
        "allowed_changed_fields": sorted(allowed_fields),
        "actual_changed_fields": changed_fields,
        "before_json": owner_json,
        "after_json": candidate_json,
        "raw_diff_path": str(diff_path),
        "raw_diff_sha256": _sha(diff_raw),
        "raw_diff_hunk_count": diff_hunks,
        "manifest_sha256": manifest_sha,
        "candidate_inventory_config_sha256": config_inventory_rows[0]["sha256"],
        "primary_plist_path": str(plist_path),
        "primary_plist_sha256": _file_sha(plist_path),
        "candidate_release_id": candidate_release_id,
        "source_roots_outside_allowed_fields_unchanged": all(
            owner_json.get(key) == candidate_json.get(key)
            for key in (set(owner_json) | set(candidate_json)) - allowed_fields
        ),
        "candidate_shared_data_root": str(candidate_shared_root),
        "owner_shared_data_root": str(owner_shared_root),
        "stage_r4_packaged_shared_data_root": str(stage_r4_shared_root),
        "owner_shared_package_file_count": len(owner_package_records),
        "stage_r4_shared_package_file_count": len(stage_r4_package_records),
        "candidate_shared_package_file_count": len(candidate_package_records),
        "shared_package_inventory_sha256": package_digest,
        "shared_package_bytes_identical_to_configured_owner_and_stage_r4": True,
        "isolated_loader_candidate_path": str(loader_path),
        "isolated_loader_candidate_sha256": _file_sha(loader_path),
        "isolated_loader_owner_sha256": _file_sha(owner_loader_path),
        "loaded_shared_module": shared_module.__name__,
        "loaded_shared_module_origin": str(module_origin),
        "loaded_shared_module_origin_sha256": _file_sha(module_origin),
        "loaded_package_module_origins": loaded_package_modules,
        "all_loaded_shared_modules_candidate_scoped": True,
        "actual_overlay_entry": None,
    }
    receipt_path = candidate_root.parent / "stage-config-identity-render-r8.json"
    _write_json(receipt_path, receipt)
    receipt["receipt_path"] = str(receipt_path)
    return receipt


def _owner_entry(
    *, owner_app: Path, relative: str, after: bytes, after_sha: str,
    diff_root: Path, source_kind: str,
) -> dict[str, Any]:
    before_path = _relative_file(owner_app, relative)
    before_raw = before_path.read_bytes() if before_path.is_file() else None
    before_sha = _sha(before_raw) if before_raw is not None else None
    if before_sha == after_sha:
        return {
            "path": relative, "classification": "SAME_ALREADY_PRESENT",
            "before_sha256": before_sha, "after_sha256": after_sha,
            "source_kind": source_kind, "diff_path": None,
        }
    diff_sha = None
    hunk_count = None
    diff_path = None
    if before_raw is not None:
        diff_raw, hunk_count = _diff(
            before_raw, after,
            before_name="before",
            after_name="after",
        )
        diff_sha = _sha(diff_raw)
        diff_path = diff_root / (relative + ".diff")
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        with diff_path.open("xb") as handle:
            handle.write(diff_raw)
    target = _relative_file(owner_app, relative)
    return {
        "path": relative,
        "classification": "CHANGED" if before_raw is not None else "ADDITION",
        "before_sha256": before_sha,
        "after_sha256": after_sha,
        "unified_diff_sha256": diff_sha,
        "unified_diff_hunk_count": hunk_count,
        "diff_path": str(diff_path) if diff_path else None,
        "source_kind": source_kind,
    }


def _tree_diff_records(
    *, before_root: Path, after_root: Path, relatives: list[str], diff_root: Path,
    source_kind: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative in sorted(set(relatives)):
        before_path = _relative_file(before_root, relative)
        after_path = _relative_file(after_root, relative)
        before_raw = before_path.read_bytes() if before_path.is_file() else None
        after_raw = after_path.read_bytes() if after_path.is_file() else None
        if after_raw is None:
            raise ValueError(f"candidate owner path is missing after integration: {relative}")
        before_sha = _sha(before_raw) if before_raw is not None else None
        after_sha = _sha(after_raw)
        if before_sha == after_sha:
            records.append({
                "path": relative, "classification": "SAME_ALREADY_PRESENT",
                "before_sha256": before_sha, "after_sha256": after_sha,
                "source_kind": source_kind, "diff_path": None,
            })
            continue
        diff_path = None
        diff_sha = None
        hunk_count = None
        diff_status = "ADDITION_NO_BEFORE_BYTES"
        if before_raw is not None:
            try:
                diff_raw, hunk_count = _diff(
                    before_raw, after_raw,
                    before_name=f"{before_root.name}/{relative}",
                    after_name=f"candidate/{relative}",
                )
            except UnicodeDecodeError:
                diff_raw = b""
                diff_status = "BINARY_OR_NON_UTF8_HASH_ONLY"
            else:
                diff_status = "TEXT_UNIFIED_DIFF"
            if diff_status == "TEXT_UNIFIED_DIFF":
                diff_sha = _sha(diff_raw)
                diff_path = diff_root / (relative + ".diff")
                diff_path.parent.mkdir(parents=True, exist_ok=True)
                with diff_path.open("xb") as handle:
                    handle.write(diff_raw)
        records.append({
            "path": relative,
            "classification": "CHANGED" if before_raw is not None else "ADDITION",
            "before_sha256": before_sha,
            "after_sha256": after_sha,
            "unified_diff_sha256": diff_sha,
            "unified_diff_hunk_count": hunk_count,
            "diff_status": diff_status,
            "diff_path": str(diff_path) if diff_path else None,
            "source_kind": source_kind,
        })
    return records


def _api_source_bytes() -> tuple[dict[str, bytes], dict[str, str]]:
    sources: dict[str, bytes] = {}
    categories: dict[str, str] = {}
    for relative, expected in API_AFTER_SHA256.items():
        source = _relative_file(REPO_ROOT, relative)
        raw = source.read_bytes()
        if _sha(raw) != expected:
            raise ValueError(f"API source hash changed from approved after SHA: {relative}")
        sources[relative] = raw
        categories[relative] = "REVIEWED_SOURCE_DELTA"

    closure = _read_json(MODULE_CLOSURE)
    frozen_root = BASE / "candidate_source_closure_frozen"
    additions = closure.get("candidate_dependency_additions")
    if not isinstance(additions, list) or len(additions) != 9:
        raise ValueError("expected the nine explicitly frozen API dependency additions")
    for row in additions:
        if not isinstance(row, dict):
            raise ValueError("invalid frozen API dependency closure row")
        relative = str(row["path"])
        expected = str(row["source_sha256"])
        frozen = frozen_root / relative
        current = _relative_file(REPO_ROOT, relative)
        frozen_raw = frozen.read_bytes()
        if _sha(frozen_raw) != expected or current.read_bytes() != frozen_raw:
            raise ValueError(f"frozen API candidate addition differs: {relative}")
        sources[relative] = frozen_raw
        categories[relative] = "FROZEN_CANDIDATE_ADDITION_ONLY"
    return sources, categories


def _phase_b_api_client_source_bytes() -> tuple[dict[str, bytes], dict[str, str]]:
    """Resolve only the independently accepted PhaseA client source bytes."""
    sources: dict[str, bytes] = {}
    categories: dict[str, str] = {}
    for relative, expected_sha in PHASE_A_CLIENT_SOURCE_SHA256.items():
        source = _relative_file(REPO_ROOT, relative)
        raw = source.read_bytes()
        if _sha(raw) != expected_sha:
            raise ValueError(f"PhaseA client source changed from its frozen accepted SHA: {relative}")
        sources[relative] = raw
        categories[relative] = "REVIEWED_PHASE_A_CLIENT_SOURCE"
    if set(sources) != set(PHASE_A_CLIENT_SOURCE_SHA256):
        raise ValueError("PhaseB API candidate source scope differs from the three reviewed PhaseA client paths")
    return sources, categories


def _validate_current_api_owner_receipt(identity: Mapping[str, Any]) -> None:
    """Require the exact live v24 owner selected for the PhaseB API-only repair."""
    expected = {
        "schema": "r8.stage_client_repair.current_api_owner.v1",
        "root": str(CURRENT_API_OWNER_ROOT),
        "app_root": str(CURRENT_API_OWNER_APP_ROOT),
        "release_id": CURRENT_API_OWNER_RELEASE_ID,
        "plist_path": str(CURRENT_API_OWNER_PLIST),
        "plist_sha256": CURRENT_API_OWNER_PLIST_SHA256,
        "backup_plist_path": str(CURRENT_API_OWNER_BACKUP_PLIST),
        "manifest_path": str(CURRENT_API_OWNER_MANIFEST),
        "manifest_sha256": CURRENT_API_OWNER_MANIFEST_SHA256,
    }
    for key, value in expected.items():
        if identity.get(key) != value:
            raise ValueError(f"current API owner receipt differs from its PhaseB pin: {key}")
    if identity.get("required_preservation") != (
        "All existing currentv24 owner bytes except scoped client/types source and fresh frontendbuild deltas; "
        "noAPIbackend/consumer/Stage/Scheduler modifications"
    ):
        raise ValueError("current API owner receipt preservation contract changed")
    fingerprints = identity.get("selected_source_fingerprints")
    if not isinstance(fingerprints, Mapping):
        raise ValueError("current API owner receipt source fingerprints are missing")
    if set(fingerprints) != set(CURRENT_API_OWNER_SELECTED_SOURCE_SHA256):
        raise ValueError("current API owner receipt source fingerprint set changed")
    for relative, expected_sha in CURRENT_API_OWNER_SELECTED_SOURCE_SHA256.items():
        row = fingerprints.get(relative)
        if not isinstance(row, Mapping) or row.get("sha256") != expected_sha:
            raise ValueError(f"current API owner receipt selected-source pin changed: {relative}")


def _load_current_api_owner_context(root: Path, api_release: Any) -> dict[str, Any]:
    """Bind a private plist copy to the exact currently deployed v24 app owner."""
    identity_path = CURRENT_API_OWNER_FOR_STAGE_CLIENT_REPAIR
    if identity_path.is_symlink() or not identity_path.is_file():
        raise ValueError("current v24 API owner receipt is missing or unsafe")
    identity = _read_json(identity_path)
    _validate_current_api_owner_receipt(identity)

    live_plist = Path(str(identity["plist_path"]))
    backup_plist = Path(str(identity["backup_plist_path"]))
    manifest_path = Path(str(identity["manifest_path"]))
    for path, expected_sha, label in (
        (live_plist, CURRENT_API_OWNER_PLIST_SHA256, "live v24 API plist"),
        (backup_plist, CURRENT_API_OWNER_PLIST_SHA256, "v24 API rollback plist"),
        (manifest_path, CURRENT_API_OWNER_MANIFEST_SHA256, "v24 API release manifest"),
    ):
        if path.is_symlink() or not path.is_file() or _file_sha(path) != expected_sha:
            raise ValueError(f"{label} no longer matches the pinned current owner")

    inputs_dir = root / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    staged_owner_plist = inputs_dir / live_plist.name
    if staged_owner_plist.exists() or staged_owner_plist.is_symlink():
        raise FileExistsError("refusing to overwrite staged current API owner plist")
    shutil.copy2(live_plist, staged_owner_plist)
    if _file_sha(staged_owner_plist) != CURRENT_API_OWNER_PLIST_SHA256:
        raise ValueError("staged current API owner plist differs from its pinned bytes")

    active = api_release.read_active_release(staged_owner_plist, role="gateway")
    live_active = api_release.read_active_release(live_plist, role="gateway")
    expected_identity = {
        "release_root": str(CURRENT_API_OWNER_ROOT),
        "app_root": str(CURRENT_API_OWNER_APP_ROOT),
        "release_id": CURRENT_API_OWNER_RELEASE_ID,
        "release_manifest_path": str(CURRENT_API_OWNER_MANIFEST),
        "release_manifest_sha256": CURRENT_API_OWNER_MANIFEST_SHA256,
    }
    for key, value in expected_identity.items():
        if active.get(key) != value or live_active.get(key) != value:
            raise ValueError(f"active API owner differs from the pinned v24 identity: {key}")
    if (active.get("api_plist_sha256") != CURRENT_API_OWNER_PLIST_SHA256
            or live_active.get("api_plist_sha256") != CURRENT_API_OWNER_PLIST_SHA256
            or api_release._base_binding(active) != api_release._base_binding(live_active)):
        raise ValueError("current v24 API pointer changed while its base identity was being captured")

    owner_app = Path(str(active["app_root"]))
    active_fingerprints: dict[str, dict[str, Any]] = {}
    for relative, expected_sha in CURRENT_API_OWNER_SELECTED_SOURCE_SHA256.items():
        source_path = api_release._safe_child(owner_app, relative, allow_missing=False)
        if source_path.is_symlink() or not source_path.is_file():
            raise ValueError(f"pinned current API owner source is missing or unsafe: {relative}")
        raw = source_path.read_bytes()
        if _sha(raw) != expected_sha:
            raise ValueError(f"pinned current API owner source changed: {relative}")
        expected_receipt = identity["selected_source_fingerprints"][relative]
        if expected_receipt.get("size_bytes") != len(raw):
            raise ValueError(f"pinned current API owner source size changed: {relative}")
        active_fingerprints[relative] = {
            "sha256": expected_sha,
            "size_bytes": len(raw),
        }
    return {
        "identity_path": str(identity_path),
        "identity_sha256": _file_sha(identity_path),
        "identity": identity,
        "live_plist_path": str(live_plist),
        "backup_plist_path": str(backup_plist),
        "staged_owner_plist_path": str(staged_owner_plist),
        "active": active,
        "selected_source_fingerprints": active_fingerprints,
    }


def _prepare_api(root: Path, source_bytes: Mapping[str, bytes], categories: Mapping[str, str]) -> dict[str, Any]:
    sys.path.insert(0, str(REPO_ROOT))
    from ops import api_release_integration as api_release
    from ops import build_release_candidate as builder

    rebase = _read_json(API_REBASE)
    if (rebase.get("current_owner_release") != "research-workbench-simplification-api-20261012-r4"
            or rebase.get("manifest_sha256") != API_BASELINE_MANIFEST_SHA
            or rebase.get("plist_sha256") != API_BACKUP_PLIST_SHA):
        raise ValueError("current API owner rebase identity or plist binding mismatch")
    backup_value = rebase.get("backup_plist")
    if not isinstance(backup_value, str) or not backup_value.strip():
        raise ValueError("current API owner rebase is missing backup_plist")
    base_plist = Path(backup_value)
    if _file_sha(base_plist) != API_BACKUP_PLIST_SHA:
        raise ValueError("immutable R4 API plist backup hash mismatch")
    api_input = root / "inputs" / "com.lexi.v35.api-only.plist"
    api_input.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(base_plist, api_input)
    active = api_release.read_active_release(api_input, role="gateway")
    if (active["release_id"] != "research-workbench-simplification-api-20261012-r4"
            or active["release_manifest_sha256"] != API_BASELINE_MANIFEST_SHA
            or rebase.get("manifest_sha256") != API_BASELINE_MANIFEST_SHA):
        raise ValueError("immutable R4 API release identity mismatch")
    owner_app = Path(active["app_root"])
    identities = rebase.get("source_identities")
    expected_identity_paths = {
        "apps/api/v35_api/app.py", "stage_center/consumer.py",
        "apps/web/src/App.vue", "apps/web/src/App.spec.ts",
        "apps/web/src/app_shell/types.ts", "apps/web/src/api/pool_stage.ts",
        "apps/web/dist/index.html",
    }
    if (not isinstance(identities, list) or len(identities) != len(expected_identity_paths)
            or {row.get("path") for row in identities if isinstance(row, dict)} != expected_identity_paths):
        raise ValueError("current API rebase source identity closure is invalid")
    for row in identities:
        relative = str(row["path"])
        path = api_release._safe_child(owner_app, relative, allow_missing=True)
        expected_exists = row.get("exists")
        if expected_exists is True:
            if path.is_symlink() or not path.is_file() or _file_sha(path) != row.get("sha256"):
                raise ValueError(f"current API owner source identity changed: {relative}")
        elif expected_exists is False:
            if path.exists() or path.is_symlink() or row.get("sha256") is not None:
                raise ValueError(f"current API owner absence identity changed: {relative}")
        else:
            raise ValueError(f"current API owner identity has invalid existence marker: {relative}")
    current_owner = api_release.read_active_release(Path(str(rebase["plist_path"])), role="gateway")
    if (current_owner["api_plist_sha256"] != rebase.get("plist_sha256")
            or api_release._base_binding(current_owner) != api_release._base_binding(active)):
        raise ValueError("current API pointer changed after its exact R4 backup was pinned")
    base_entries = {str(row["path"]): row for row in active["inventory"]}
    diff_root = root / "owner-base-diffs" / "api"
    entries: list[dict[str, Any]] = []
    owner_diff_records: list[dict[str, Any]] = []
    for relative in sorted(source_bytes):
        raw = source_bytes[relative]
        after_sha = _sha(raw)
        row = _owner_entry(
            owner_app=Path(active["app_root"]), relative=relative, after=raw,
            after_sha=after_sha, diff_root=diff_root, source_kind=categories[relative],
        )
        owner_diff_records.append(row)
        if row["classification"] == "SAME_ALREADY_PRESENT":
            continue
        entries.append({
            "path": relative,
            "before_sha256": row["before_sha256"],
            "after_sha256": after_sha,
            "unified_diff_sha256": row.get("unified_diff_sha256"),
            "unified_diff_hunk_count": row.get("unified_diff_hunk_count"),
        })

    delta_receipt = {
        "schema_version": api_release.DELTA_SCHEMA_VERSION,
        "base": api_release._base_binding(active),
        "target_role": "gateway",
        "base_role": "gateway",
        "entries": entries,
        "source_categories": categories,
        "owner_base_full_diffs": owner_diff_records,
    }
    delta_path = root / "api" / "api-integration-delta-r8.json"
    _write_json(delta_path, delta_receipt)
    untracked = sorted(
        relative for relative in source_bytes
        if relative not in base_entries
    )
    candidate_id = "research-workbench-simplification-api-20261013-r8-candidate"
    candidate_root = root / "api" / candidate_id
    builder_receipt = root / "api" / "api-build-receipt-r8.json"
    builder._guard_candidate_root(
        candidate_root,
        source_root=REPO_ROOT,
        formal_release_root=builder.DEFAULT_FORMAL_RELEASE_ROOT,
    )
    candidate_root.mkdir(parents=True, exist_ok=False)
    api_marker = candidate_root / ".candidate-build-in-progress"
    api_marker.write_text("owner-candidate-preparation-incomplete\n", encoding="utf-8")
    integration = api_release.build_integrated_app(
        active_api_plist_path=api_input,
        source_root=REPO_ROOT,
        candidate_root=candidate_root,
        delta_receipt_path=delta_path,
        explicit_untracked_paths=untracked,
        role="gateway",
        base_role="gateway",
    )
    candidate_app = candidate_root / "app"
    frontend_build = _reuse_canonical_frontend(root, candidate_app, api_release)
    frontend_delta = _register_generated_frontend_api_delta(
        root=root,
        api_candidate_root=candidate_root,
        active_app=Path(active["app_root"]),
        candidate_app=candidate_app,
        api_release=api_release,
        integration=integration,
        frontend_build=frontend_build,
    )
    frontend_build["api_integration_generated_delta"] = frontend_delta
    frontend_receipt_path = Path(str(frontend_build["receipt_path"]))
    frontend_receipt_payload = _read_json(frontend_receipt_path)
    frontend_receipt_payload["api_integration_generated_delta"] = frontend_delta
    frontend_receipt_path.write_text(
        json.dumps(frontend_receipt_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    frontend_build["receipt_sha256"] = _file_sha(frontend_receipt_path)
    app_inventory = api_release.inventory_tree(candidate_app)
    dist_inventory = [
        row for row in app_inventory
        if str(row["path"]) == "apps/web/dist"
        or str(row["path"]).startswith("apps/web/dist/")
    ]
    api_delta_paths = {str(row["path"]) for row in integration["delta_entries"]}
    owner_non_frontend = {
        path: row for path, row in base_entries.items()
        if path not in api_delta_paths
    }
    candidate_by_path = {str(row["path"]): row for row in app_inventory}
    candidate_non_frontend = {
        path: row for path, row in candidate_by_path.items()
        if path not in api_delta_paths
    }
    if owner_non_frontend != candidate_non_frontend:
        missing = sorted(set(owner_non_frontend) - set(candidate_non_frontend))
        extra = sorted(set(candidate_non_frontend) - set(owner_non_frontend))
        changed = sorted(
            path for path in set(owner_non_frontend) & set(candidate_non_frontend)
            if owner_non_frontend[path] != candidate_non_frontend[path]
        )
        raise ValueError(
            "API candidate changed owner bytes outside the explicit API delta and generated frontend dist: "
            f"missing={missing} extra={extra} changed={changed}"
        )
    frontend_owner_preservation = {
        "status": "PASS",
        "active_api_owner_release_id": active["release_id"],
        "active_api_owner_manifest_sha256": active["release_manifest_sha256"],
        "owner_non_delta_entry_count_after_generated_frontend_delta": len(owner_non_frontend),
        "candidate_non_delta_entry_count_after_generated_frontend_delta": len(candidate_non_frontend),
        "owner_non_frontend_inventory_sha256": api_release.inventory_digest(sorted(owner_non_frontend.values(), key=lambda row: str(row["path"]))),
        "candidate_non_frontend_inventory_sha256": api_release.inventory_digest(sorted(candidate_non_frontend.values(), key=lambda row: str(row["path"]))),
        "excluded_exact_api_delta_paths": sorted(api_delta_paths),
        "separate_candidate_frontend_dist_delta": True,
        "all_other_owner_bytes_exact": True,
    }
    role_contract = api_release.module_role_contract()["roles"]["gateway"]
    candidate_manifest = {
        "schema_version": builder.SCHEMA_VERSION,
        "generated_at": builder.utc_now(),
        "candidate_status": "READY_FOR_REVIEW",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "source": {
            "active_role_plist": str(api_input),
            "api_integration_delta_receipt": str(delta_path),
            "active_release_bytes_copied": True,
            "source_workspace_full_tree_copied": False,
            "frontend_dist_from_active_release": False,
            "canonical_frontend_build_receipt_path": frontend_build["receipt_path"],
            "canonical_frontend_build_receipt_sha256": frontend_build["receipt_sha256"],
            "owner_non_frontend_preservation_after_frontend_build": frontend_owner_preservation,
        },
        "api_integration": integration,
        "candidate": {
            "root": str(candidate_root),
            "app_root": str(candidate_app),
            "release_id": candidate_id,
            "module_role": "gateway",
            "formal_release_root": str(builder.DEFAULT_FORMAL_RELEASE_ROOT),
            "data_copy_performed": False,
            "runtime_venv_copied": False,
            "ignored_runtime_data_copied": False,
        },
        "role_contract": role_contract,
        "application_inventory": {
            "entry_count": len(app_inventory),
            "aggregate_sha256": api_release.inventory_digest(app_inventory),
            "entries": app_inventory,
        },
        "frontend_dist": {
            "entry_count": len(dist_inventory),
            "aggregate_sha256": api_release.inventory_digest(dist_inventory),
            "entries": dist_inventory,
            "preserved_from_active_release": False,
            "current_workspace_dist_overlaid": False,
            "candidate_built_from_canonical_source_graph": True,
            "candidate_build_receipt_path": frontend_build["receipt_path"],
            "candidate_build_receipt_sha256": frontend_build["receipt_sha256"],
            "active_r4_dist_replaced_as_separate_frontend_delta": True,
        },
        "verification_gaps": [
            "candidate API was not activated or restarted",
            "current live pointer must be compare-and-swapped against its then-current owner before activation",
            "API, browser, and natural-slot verification remain CANNOT_CONFIRM",
        ],
    }
    manifest_path = candidate_root / "release-manifest.json"
    builder._json_dump(manifest_path, candidate_manifest)
    manifest_sha = builder.sha256_file(manifest_path)
    cutover = builder.render_module_cutover(
        source_active_plist_path=api_input,
        candidate_root=candidate_root,
        release_id=candidate_id,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha,
        role="gateway",
        base_role="gateway",
        source_root=REPO_ROOT,
        formal_release_root=builder.DEFAULT_FORMAL_RELEASE_ROOT,
    )
    api_marker.unlink()
    built = {
        "candidate_status": candidate_manifest["candidate_status"],
        "manifest_sha256": manifest_sha,
        "application_inventory": candidate_manifest["application_inventory"],
        "api_integration": integration,
        "cutover": cutover,
    }
    candidate_manifest = _read_json(candidate_root / "release-manifest.json")
    candidate_inventory = {str(row["path"]): row for row in candidate_manifest["application_inventory"]["entries"]}
    if any(candidate_inventory.get(path, {}).get("sha256") != _sha(raw)
           for path, raw in source_bytes.items()):
        raise ValueError("API candidate is missing a hashed owner delta")

    runtime_smoke = _verify_api_candidate_routes(candidate_app, root / "api" / "runtime-smoke")
    activebase_verification = api_release.verify_api_release_candidate(
        candidate_root=candidate_root,
        active_api_plist_path=Path(str(rebase["plist_path"])),
        expected_manifest_sha256=manifest_sha,
        active_pointer="base",
        role="gateway",
        base_role="gateway",
    )
    built["activebase_verification"] = activebase_verification
    _write_json(builder_receipt, {
        "schema_version": "r8.api_owner_candidate_receipt.v1",
        "candidate_status": built["candidate_status"],
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "activebase_verification": activebase_verification,
        "candidate_root": str(candidate_root),
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "delta_paths": [row["path"] for row in integration["delta_entries"]],
        "non_delta_active_release_bytes_preserved": integration["non_delta_active_release_bytes_preserved"],
        "cutover_plan": cutover["plan_path"],
        "staged_plist": cutover["candidate_plist"],
        "active_plist_changed": False,
        "launchctl_called": False,
        "candidate_testclient_smoke_status": runtime_smoke["status"],
    })

    batch4 = _read_json(BASE / "batch4_writer" / "BUILD_BUNDLE_SHA_R8.json")
    b4_assets = list(batch4.get("generated_dist_files", []))
    if len(b4_assets) != 11:
        raise ValueError("B4 frontend asset receipt must contain its exact 11 generated files")
    frontend_rows = []
    for row in b4_assets:
        relative = str(row["path"]).removeprefix("apps/web/dist/")
        active_relative = "apps/web/dist/" + relative
        active_row = candidate_inventory.get(active_relative)
        owner_row = base_entries.get(active_relative)
        frontend_rows.append({
            "path": active_relative,
            "batch4_sha256": row["sha256"],
            "active_r4_sha256": owner_row.get("sha256") if owner_row else None,
            "candidate_canonical_build_sha256": active_row.get("sha256") if active_row else None,
            "classification": (
                "SAME_HASH_AS_B4_BUILD_RECEIPT" if active_row and active_row.get("sha256") == row["sha256"]
                else "FRESH_CANONICAL_BUILD_DIFFERS_FROM_B4_RECEIPT" if active_row
                else "B4_RECEIPT_PATH_ABSENT_FROM_CANONICAL_BUILD"
            ),
        })
    report = {
        "schema_version": "r8.api_owner_candidate_preparation.v1",
        "candidate_status": built.get("candidate_status"),
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "activebase_verification": activebase_verification,
        "immutable_owner_base": {
            "release_id": active["release_id"],
            "manifest_path": active["release_manifest_path"],
            "manifest_sha256": active["release_manifest_sha256"],
            "backup_plist": str(base_plist),
            "backup_plist_sha256": _file_sha(base_plist),
            "current_live_owner_at_future_activation": "CAS_REQUIRED",
        },
        "candidate": {
            "root": str(candidate_root),
            "app_root": str(candidate_app),
            "release_id": candidate_id,
            "manifest_sha256": built["manifest_sha256"],
        },
        "reviewed_source_delta_and_frozen_additions": owner_diff_records,
        "non_delta_active_release_bytes_preserved": frontend_owner_preservation["all_other_owner_bytes_exact"],
        "non_delta_active_release_bytes_preserved_scope": "All latest API R4 non-frontend non-delta entries; apps/web/dist is a separately pinned canonical source build delta.",
        "non_delta_path_count": candidate_manifest["api_integration"]["non_delta_entry_count"],
        "explicit_untracked_paths": untracked,
        "frontend_assets": {
            "batch4_generated_asset_category": "SEPARATE_PRIOR_DIST_RECEIPT_COMPARED_TO_FRESH_CANONICAL_SOURCE_BUILD",
            "batch4_generated_files": frontend_rows,
            "api_active_r4_dist_entry_count": sum(path.startswith("apps/web/dist/") for path in base_entries),
            "fresh_candidate_dist_entry_count": sum(path.startswith("apps/web/dist/") for path in candidate_inventory),
            "r4_assets_preserved_by_owner_base_copy": False,
            "canonical_build_receipt": frontend_build,
            "owner_non_frontend_preservation": frontend_owner_preservation,
        },
        "candidate_only_testclient": runtime_smoke,
        "static_unavailable_or_running_claims": "CANNOT_CONFIRM",
        "build_receipt_path": str(builder_receipt),
        "delta_receipt_path": str(delta_path),
    }
    report_path = root / "api" / "api-owner-candidate-report-r8.json"
    _write_json(report_path, report)
    return {"report": report, "report_path": str(report_path), "build_receipt": str(builder_receipt)}


def _verify_api_candidate_routes(candidate_app: Path, smoke_root: Path) -> dict[str, Any]:
    """Exercise the candidate app's configured-source routes with synthetic pools."""
    smoke_root.mkdir(parents=True, exist_ok=False)
    source_root = smoke_root / "source"
    data_root = smoke_root / "api-data"
    smoke_cwd = smoke_root / "cwd"
    smoke_cwd.mkdir()
    script = smoke_root / "candidate_testclient_smoke.py"
    code = '''from __future__ import annotations
import hashlib
import json
import os
import sys
from pathlib import Path
from fastapi.testclient import TestClient
from apps.api.v35_api.app import create_app
from infrastructure.preselection_pool_store import PreselectionPoolStore

DATE = "20261008"
source_root = Path(sys.argv[1])
data_root = Path(sys.argv[2])
pool_id = "a_d1_premarket_pool"
rows = [{
    "symbol": "A.000001", "code": "A.000001", "market": "A",
    "pool_id": pool_id, "pool_rank": 1, "trade_date": DATE,
    "target_date": DATE, "recommendation_status": "WATCH_ONLY",
    "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
}]
artifact = {
    "schema_version": "v3_5.preselection_pool.v1", "trade_date": DATE,
    "pool_id": pool_id, "display_name": pool_id, "market": "A", "status": "READY",
    "producer_id": "r8_candidate_testclient", "source_role": "RAW_SOURCE",
    "source_path": f"test/{DATE}/{pool_id}.json",
    "source_sha256": hashlib.sha256(pool_id.encode()).hexdigest(), "rows": rows,
    "cannot_confirm": [], "production_allowed": False, "buy_gate_updated": False,
    "orders_sent": False,
}
PreselectionPoolStore(source_root).materialize(artifact)
lock_path = source_root / "preselection_pools" / ".materialize.lock"
descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    handle.write(json.dumps({"schema_version": "v3_5_interprocess_lock.v1", "pid": 2147483647, "token": "RELEASED"}, separators=(",", ":")))
client = TestClient(create_app(data_root=data_root, preselection_source_root=source_root, current_date=DATE))
pool_response = client.get("/api/v3/preselection-pools", params={"date": DATE, "limit": 200})
assert pool_response.status_code == 200, pool_response.text
pool_body = pool_response.json()
legacy = pool_body["pool_source_bindings"][pool_id]
evidence = pool_body["pool_source_evidence"]["pools"][pool_id]
assert legacy["physical_source_root"] == str(source_root)
assert legacy["physical_status"] == "TRIO_VERIFIED"
assert evidence["status"] == "VERIFIED" and len(evidence["pool_sha256"]) == 64
date_response = client.get("/api/v1/runs/date-list", params={"date": DATE})
assert date_response.status_code == 200, date_response.text
date_body = date_response.json()
assert date_body["ok"] is True and DATE in date_body["dates"]
date_evidence = date_body["independent_pool_evidence"][DATE]["pools"][pool_id]
assert date_evidence["status"] == "VERIFIED"
assert date_evidence["physical_source_root"] == str(source_root)
print(json.dumps({"configured_pool_route": "PASS", "date_list_route": "PASS", "legacy_pool_source_bindings": "PRESERVED", "pool_source_evidence": evidence["status"], "independent_pool_evidence": date_evidence["status"]}, sort_keys=True))
'''
    with script.open("x", encoding="utf-8") as handle:
        handle.write(code)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join((str(candidate_app / "upstreams"), str(candidate_app)))
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [sys.executable, str(script), str(source_root), str(data_root)]
    completed = subprocess.run(command, cwd=smoke_cwd, env=environment,
                               capture_output=True, text=True, check=False)
    log_path = smoke_root / "candidate_testclient_smoke.log"
    with log_path.open("x", encoding="utf-8") as handle:
        handle.write("COMMAND: " + json.dumps(command, ensure_ascii=False) + "\n")
        handle.write("RETURN_CODE: " + str(completed.returncode) + "\n")
        handle.write("STDOUT:\n" + completed.stdout)
        handle.write("STDERR:\n" + completed.stderr)
    if completed.returncode != 0:
        raise RuntimeError(f"candidate-only API TestClient failed; see {log_path}")
    payload = json.loads(completed.stdout)
    return {
        "status": "PASS",
        "candidate_app": str(candidate_app),
        "routes": payload,
        "script_path": str(script),
        "script_sha256": _file_sha(script),
        "log_path": str(log_path),
        "source_root": str(source_root),
        "data_root": str(data_root),
        "synthetic_fixture_only": True,
    }


def _verify_stage_client_candidate_plist(
    *, source_plist_path: Path, staged_record: Mapping[str, Any],
    candidate_root: Path, candidate_release_id: str, manifest_sha256: str,
    api_release: Any,
) -> dict[str, Any]:
    """Prove a staged gateway plist changes only the candidate binding."""
    staged_path = Path(str(staged_record.get("path", "")))
    if staged_path.is_symlink() or not staged_path.is_file():
        raise ValueError("staged API candidate plist is missing or unsafe")
    if _file_sha(staged_path) != staged_record.get("sha256"):
        raise ValueError("staged API candidate plist SHA differs from its cutover plan")
    source_payload = plistlib.loads(source_plist_path.read_bytes())
    staged_payload = plistlib.loads(staged_path.read_bytes())
    if not isinstance(source_payload, dict) or not isinstance(staged_payload, dict):
        raise ValueError("staged API candidate plist payload is not an object")

    for key in SCHEDULER_IDENTITY_SCHEDULE_FIELDS:
        if source_payload.get(key) != staged_payload.get(key):
            raise ValueError(f"staged API candidate changed LaunchAgent schedule field: {key}")
    if source_payload.get("Label") != staged_payload.get("Label"):
        raise ValueError("staged API candidate changed the gateway LaunchAgent label")
    mutable_top_level = {"Label", "ProgramArguments", "WorkingDirectory", "EnvironmentVariables"}
    for key in (set(source_payload) | set(staged_payload)) - mutable_top_level:
        if source_payload.get(key) != staged_payload.get(key):
            raise ValueError(f"staged API candidate changed an unrelated LaunchAgent field: {key}")

    source_environment = source_payload.get("EnvironmentVariables", {})
    staged_environment = staged_payload.get("EnvironmentVariables", {})
    if not isinstance(source_environment, Mapping) or not isinstance(staged_environment, Mapping):
        raise ValueError("staged API candidate LaunchAgent environment is invalid")
    allowed_environment_rebindings = {
        "V35_APP_ROOT": str(candidate_root / "app"),
        "PYTHONPATH": f"{candidate_root / 'app' / 'upstreams'}:{candidate_root / 'app'}",
        "V35_RELEASE_ID": candidate_release_id,
        "V35_RELEASE_MANIFEST_PATH": str(candidate_root / "release-manifest.json"),
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha256,
    }
    role_contract = api_release.module_role_contract()["roles"]["gateway"]
    allowed_identity_values = {
        **allowed_environment_rebindings,
        "V35_API_ROLE": "gateway",
        "V35_API_PORT": str(role_contract["port"]),
    }
    if set(source_environment) - set(staged_environment):
        raise ValueError("staged API candidate removed a LaunchAgent environment binding")
    unexpected_environment_additions = set(staged_environment) - set(source_environment) - {"V35_API_ROLE", "V35_API_PORT"}
    if unexpected_environment_additions:
        raise ValueError("staged API candidate added an unapproved LaunchAgent environment binding")
    for key, value in source_environment.items():
        expected = allowed_identity_values.get(key, value)
        if staged_environment.get(key) != expected:
            raise ValueError(f"staged API candidate changed an external LaunchAgent environment value: {key}")
    for key in {"V35_API_ROLE", "V35_API_PORT"} & set(staged_environment):
        if staged_environment[key] != allowed_identity_values[key]:
            raise ValueError(f"staged API candidate gateway role binding changed: {key}")

    allowed_argument_keys = set(allowed_identity_values)

    def unbound_arguments(payload: Mapping[str, Any]) -> list[Any]:
        arguments = payload.get("ProgramArguments")
        if not isinstance(arguments, list):
            raise ValueError("staged API candidate must retain ProgramArguments")
        result = []
        for item in arguments:
            key = item.partition("=")[0] if isinstance(item, str) and "=" in item else None
            if key not in allowed_argument_keys:
                result.append(item)
        return result

    if unbound_arguments(source_payload) != unbound_arguments(staged_payload):
        raise ValueError("staged API candidate changed non-identity ProgramArguments")
    source_working_directory = source_payload.get("WorkingDirectory")
    if source_working_directory is None or staged_payload.get("WorkingDirectory") != str(candidate_root / "app"):
        raise ValueError("staged API candidate WorkingDirectory is not the candidate app root")

    staged_identity = api_release.read_active_release(staged_path, role="gateway")
    if (staged_identity.get("release_root") != str(candidate_root)
            or staged_identity.get("app_root") != str(candidate_root / "app")
            or staged_identity.get("release_id") != candidate_release_id
            or staged_identity.get("release_manifest_sha256") != manifest_sha256):
        raise ValueError("staged API candidate plist does not bind to its exact candidate manifest")
    return {
        "status": "PASS",
        "path": str(staged_path),
        "sha256": _file_sha(staged_path),
        "schedule_fields_preserved": list(SCHEDULER_IDENTITY_SCHEDULE_FIELDS),
        "external_environment_values_preserved": True,
        "environment_rebindings": allowed_environment_rebindings,
        "program_arguments_outside_identity_preserved": True,
        "working_directory_candidate_app": str(candidate_root / "app"),
        "candidate_manifest_binding": {
            "release_id": staged_identity["release_id"],
            "manifest_path": staged_identity["release_manifest_path"],
            "manifest_sha256": staged_identity["release_manifest_sha256"],
        },
    }


def _frontend_source_owner_comparison(
    *, source_inputs: list[Mapping[str, Any]], owner_entries: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    graph_paths: set[str] = set()
    for row in source_inputs:
        relative = "apps/web/" + str(row["path"])
        graph_paths.add(relative)
        owner_row = owner_entries.get(relative)
        source_sha = row.get("sha256")
        if owner_row is None:
            classification = "CANONICAL_GRAPH_ADDITION_TO_CURRENT_OWNER_SOURCE"
        elif owner_row.get("sha256") == source_sha:
            classification = "SAME_AS_CURRENT_OWNER_SOURCE"
        else:
            classification = "CANONICAL_GRAPH_DIFFERS_FROM_CURRENT_OWNER_SOURCE"
        records.append({
            "path": relative,
            "classification": classification,
            "current_owner_sha256": owner_row.get("sha256") if owner_row else None,
            "canonical_source_sha256": source_sha,
            "allowed_phase_a_client_path": relative in PHASE_A_CLIENT_SOURCE_SHA256,
        })
    owner_graph_paths = {
        path for path in owner_entries
        if path.startswith("apps/web/src/") or path.startswith("apps/web/public/")
        or path in {"apps/web/" + item for item in FRONTEND_BUILD_INPUT_FILES}
    }
    for relative in sorted(owner_graph_paths - graph_paths):
        records.append({
            "path": relative,
            "classification": "CURRENT_OWNER_SOURCE_NOT_IN_CANONICAL_GRAPH",
            "current_owner_sha256": owner_entries[relative].get("sha256"),
            "canonical_source_sha256": None,
            "allowed_phase_a_client_path": relative in PHASE_A_CLIENT_SOURCE_SHA256,
        })
    return sorted(records, key=lambda row: str(row["path"]))


def _prepare_api_stage_client_candidate(root: Path) -> dict[str, Any]:
    """Build the scoped client-repair API candidate on the pinned live v24 owner."""
    root = root.resolve()
    if not root.is_relative_to(BASE.resolve()) or root == CURRENT_API_OWNER_ROOT.resolve():
        raise ValueError("PhaseB API candidate output must be separate and contained in the R8 receipt workspace")
    if not root.is_dir() or (root / "api").exists() or (root / "api").is_symlink():
        raise ValueError("PhaseB API candidate output root is missing or already contains API output")
    if any(path.is_symlink() for path in (root, *root.parents) if path != Path(path.anchor)):
        raise ValueError("PhaseB API candidate output path contains a symlink")

    sys.path.insert(0, str(REPO_ROOT))
    from ops import api_release_integration as api_release
    from ops import build_release_candidate as builder

    owner_context = _load_current_api_owner_context(root, api_release)
    active = owner_context["active"]
    live_plist = Path(owner_context["live_plist_path"])
    base_plist = Path(owner_context["backup_plist_path"])
    source_bytes, categories = _phase_b_api_client_source_bytes()
    if set(source_bytes) != set(PHASE_A_CLIENT_SOURCE_SHA256):
        raise ValueError("PhaseB API candidate source paths are broader than the reviewed PhaseA client scope")

    base_entries = {str(row["path"]): row for row in active["inventory"]}
    owner_diff_records: list[dict[str, Any]] = []
    delta_entries: list[dict[str, Any]] = []
    for relative, raw in sorted(source_bytes.items()):
        row = _owner_entry(
            owner_app=Path(active["app_root"]), relative=relative, after=raw,
            after_sha=_sha(raw), diff_root=root / "owner-base-diffs" / "api",
            source_kind=categories[relative],
        )
        owner_diff_records.append(row)
        if row["classification"] == "SAME_ALREADY_PRESENT":
            continue
        delta_entries.append({
            "path": relative,
            "before_sha256": row["before_sha256"],
            "after_sha256": row["after_sha256"],
            "unified_diff_sha256": row.get("unified_diff_sha256"),
            "unified_diff_hunk_count": row.get("unified_diff_hunk_count"),
        })
    delta_entries.sort(key=lambda row: str(row["path"]))
    if not delta_entries:
        raise ValueError("PhaseB API candidate has no source delta against the pinned v24 owner")

    delta_receipt = {
        "schema_version": api_release.DELTA_SCHEMA_VERSION,
        "base": api_release._base_binding(active),
        "target_role": "gateway",
        "base_role": "gateway",
        "entries": delta_entries,
        "source_categories": categories,
        "owner_base_full_diffs": owner_diff_records,
    }
    delta_path = root / "api" / "api-integration-delta-r8.json"
    _write_json(delta_path, delta_receipt)
    untracked = sorted(relative for relative in source_bytes if relative not in base_entries)
    if set(untracked) != {
        "apps/web/src/api/pool_stage.ts",
        "apps/web/src/api/pool_stage.spec.ts",
        "apps/web/src/app_shell/types.ts",
    }:
        raise ValueError("pinned v24 owner frontend source absence set changed")

    candidate_id = API_STAGE_CLIENT_CANDIDATE_ID
    if candidate_id == active["release_id"]:
        raise ValueError("PhaseB API candidate release id cannot reuse the active v24 owner identity")
    candidate_root = root / "api" / candidate_id
    builder_receipt = root / "api" / "api-build-receipt-r8.json"
    builder._guard_candidate_root(
        candidate_root,
        source_root=REPO_ROOT,
        formal_release_root=builder.DEFAULT_FORMAL_RELEASE_ROOT,
    )
    candidate_root.mkdir(parents=True, exist_ok=False)
    api_marker = candidate_root / ".candidate-build-in-progress"
    api_marker.write_text("stage-client-api-candidate-preparation-incomplete\n", encoding="utf-8")
    integration = api_release.build_integrated_app(
        active_api_plist_path=Path(owner_context["staged_owner_plist_path"]),
        source_root=REPO_ROOT,
        candidate_root=candidate_root,
        delta_receipt_path=delta_path,
        explicit_untracked_paths=untracked,
        role="gateway",
        base_role="gateway",
    )
    candidate_app = candidate_root / "app"
    frontend_build = _compile_canonical_frontend(
        root, candidate_app, api_release,
        purpose="phase-b-stage-client",
        required_source_shas=PHASE_A_CLIENT_SOURCE_SHA256,
    )
    frontend_delta = _register_generated_frontend_api_delta(
        root=root,
        api_candidate_root=candidate_root,
        active_app=Path(active["app_root"]),
        candidate_app=candidate_app,
        api_release=api_release,
        integration=integration,
        frontend_build=frontend_build,
        source_category="GENERATED_CANONICAL_PHASE_B_FRONTEND_BUILD",
    )
    frontend_build["api_integration_generated_delta"] = frontend_delta
    frontend_receipt_path = Path(str(frontend_build["receipt_path"]))
    frontend_receipt_payload = _read_json(frontend_receipt_path)
    frontend_receipt_payload["api_integration_generated_delta"] = frontend_delta
    frontend_receipt_path.write_text(
        json.dumps(frontend_receipt_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    frontend_build["receipt_sha256"] = _file_sha(frontend_receipt_path)

    app_inventory = api_release.inventory_tree(candidate_app)
    dist_inventory = [
        row for row in app_inventory
        if str(row["path"]) == "apps/web/dist" or str(row["path"]).startswith("apps/web/dist/")
    ]
    api_delta_paths = {str(row["path"]) for row in integration["delta_entries"]}
    owner_non_delta = {path: row for path, row in base_entries.items() if path not in api_delta_paths}
    candidate_by_path = {str(row["path"]): row for row in app_inventory}
    candidate_non_delta = {
        path: row for path, row in candidate_by_path.items() if path not in api_delta_paths
    }
    if owner_non_delta != candidate_non_delta:
        missing = sorted(set(owner_non_delta) - set(candidate_non_delta))
        extra = sorted(set(candidate_non_delta) - set(owner_non_delta))
        changed = sorted(
            path for path in set(owner_non_delta) & set(candidate_non_delta)
            if owner_non_delta[path] != candidate_non_delta[path]
        )
        raise ValueError(
            "PhaseB API candidate changed current v24 owner bytes outside client and generated frontend deltas: "
            f"missing={missing} extra={extra} changed={changed}"
        )
    owner_preservation = {
        "status": "PASS",
        "active_api_owner_release_id": active["release_id"],
        "active_api_owner_manifest_sha256": active["release_manifest_sha256"],
        "owner_application_entry_count": len(base_entries),
        "candidate_application_entry_count": len(app_inventory),
        "owner_non_delta_entry_count": len(owner_non_delta),
        "candidate_non_delta_entry_count": len(candidate_non_delta),
        "owner_non_delta_inventory_sha256": api_release.inventory_digest(
            sorted(owner_non_delta.values(), key=lambda row: str(row["path"]))
        ),
        "candidate_non_delta_inventory_sha256": api_release.inventory_digest(
            sorted(candidate_non_delta.values(), key=lambda row: str(row["path"]))
        ),
        "exact_delta_paths": sorted(api_delta_paths),
        "all_other_current_v24_owner_bytes_exact": True,
    }

    source_backend_consumer = {}
    for relative, expected_sha in (
        ("apps/api/v35_api/app.py", CURRENT_API_OWNER_SELECTED_SOURCE_SHA256["apps/api/v35_api/app.py"]),
        ("stage_center/consumer.py", CURRENT_API_OWNER_SELECTED_SOURCE_SHA256["stage_center/consumer.py"]),
    ):
        owner_row = base_entries.get(relative)
        candidate_row = candidate_by_path.get(relative)
        if (owner_row is None or candidate_row != owner_row
                or owner_row.get("sha256") != expected_sha):
            raise ValueError(f"API backend or Stage consumer changed in PhaseB candidate: {relative}")
        source_backend_consumer[relative] = {
            "sha256": expected_sha,
            "current_owner_equals_candidate": True,
        }

    source_records = list(frontend_build["source_inputs"])
    graph_owner_comparison = _frontend_source_owner_comparison(
        source_inputs=source_records, owner_entries=base_entries,
    )
    phase_a_graph_rows = [
        row for row in source_records
        if "apps/web/" + str(row["path"]) in PHASE_A_CLIENT_SOURCE_SHA256
    ]
    if {"apps/web/" + str(row["path"]): row["sha256"] for row in phase_a_graph_rows} != PHASE_A_CLIENT_SOURCE_SHA256:
        raise ValueError("fresh canonical frontend graph does not contain the exact PhaseA client source triplet")

    role_contract = api_release.module_role_contract()["roles"]["gateway"]
    candidate_manifest = {
        "schema_version": builder.SCHEMA_VERSION,
        "generated_at": builder.utc_now(),
        "candidate_status": "READY_FOR_REVIEW",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "source": {
            "active_role_plist": owner_context["staged_owner_plist_path"],
            "current_owner_identity_receipt": owner_context["identity_path"],
            "current_owner_identity_receipt_sha256": owner_context["identity_sha256"],
            "api_integration_delta_receipt": str(delta_path),
            "active_release_bytes_copied": True,
            "source_workspace_full_tree_copied": False,
            "frontend_dist_from_active_release": False,
            "canonical_frontend_build_receipt_path": frontend_build["receipt_path"],
            "canonical_frontend_build_receipt_sha256": frontend_build["receipt_sha256"],
            "owner_non_delta_preservation": owner_preservation,
        },
        "api_integration": integration,
        "candidate": {
            "root": str(candidate_root),
            "app_root": str(candidate_app),
            "release_id": candidate_id,
            "module_role": "gateway",
            "formal_release_root": str(builder.DEFAULT_FORMAL_RELEASE_ROOT),
            "data_copy_performed": False,
            "runtime_venv_copied": False,
            "ignored_runtime_data_copied": False,
        },
        "role_contract": role_contract,
        "application_inventory": {
            "entry_count": len(app_inventory),
            "aggregate_sha256": api_release.inventory_digest(app_inventory),
            "entries": app_inventory,
        },
        "frontend_dist": {
            "entry_count": len(dist_inventory),
            "aggregate_sha256": api_release.inventory_digest(dist_inventory),
            "entries": dist_inventory,
            "preserved_from_active_release": False,
            "current_workspace_dist_copied": False,
            "candidate_built_from_canonical_source_graph": True,
            "candidate_build_receipt_path": frontend_build["receipt_path"],
            "candidate_build_receipt_sha256": frontend_build["receipt_sha256"],
            "current_owner_unreferenced_dist_assets_preserved": True,
        },
        "verification_gaps": [
            "candidate API was not activated or restarted",
            "current live pointer must be compared with its exact owner before any future activation",
            "actual candidate API, browser page, and natural-slot verification remain CANNOT_CONFIRM",
        ],
    }
    manifest_path = candidate_root / "release-manifest.json"
    builder._json_dump(manifest_path, candidate_manifest)
    manifest_sha = builder.sha256_file(manifest_path)
    cutover = builder.render_module_cutover(
        source_active_plist_path=Path(owner_context["staged_owner_plist_path"]),
        candidate_root=candidate_root,
        release_id=candidate_id,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha,
        role="gateway",
        base_role="gateway",
        source_root=REPO_ROOT,
        formal_release_root=builder.DEFAULT_FORMAL_RELEASE_ROOT,
    )
    api_marker.unlink()

    activebase_verification = api_release.verify_api_release_candidate(
        candidate_root=candidate_root,
        active_api_plist_path=live_plist,
        expected_manifest_sha256=manifest_sha,
        active_pointer="base",
        role="gateway",
        base_role="gateway",
    )
    staged_plist_verification = _verify_stage_client_candidate_plist(
        source_plist_path=Path(owner_context["staged_owner_plist_path"]),
        staged_record=cutover["candidate_plist"],
        candidate_root=candidate_root,
        candidate_release_id=candidate_id,
        manifest_sha256=manifest_sha,
        api_release=api_release,
    )
    runtime_smoke = _verify_api_candidate_routes(candidate_app, root / "api" / "runtime-smoke")
    builder_receipt = root / "api" / "api-build-receipt-r8.json"
    _write_json(builder_receipt, {
        "schema_version": "r8.api_stage_client_candidate_receipt.v1",
        "candidate_status": "READY_FOR_REVIEW",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "activebase_verification": activebase_verification,
        "staged_plist_verification": staged_plist_verification,
        "candidate_root": str(candidate_root),
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "api_source_delta_paths": sorted(source_bytes),
        "generated_frontend_delta_paths": frontend_delta["generated_delta_paths"],
        "owner_non_delta_bytes_preserved": owner_preservation["all_other_current_v24_owner_bytes_exact"],
        "cutover_plan": cutover["plan_path"],
        "staged_plist": cutover["candidate_plist"],
        "active_plist_changed": False,
        "launchctl_called": False,
        "candidate_testclient_smoke_status": runtime_smoke["status"],
    })

    report = {
        "schema_version": "r8.api_stage_client_candidate_preparation.v1",
        "candidate_status": "READY_FOR_REVIEW",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "immutable_current_owner": {
            "identity_receipt_path": owner_context["identity_path"],
            "identity_receipt_sha256": owner_context["identity_sha256"],
            "release_id": active["release_id"],
            "release_root": active["release_root"],
            "app_root": active["app_root"],
            "manifest_path": active["release_manifest_path"],
            "manifest_sha256": active["release_manifest_sha256"],
            "live_plist_path": owner_context["live_plist_path"],
            "live_plist_sha256": active["api_plist_sha256"],
            "matching_backup_plist_path": owner_context["backup_plist_path"],
            "matching_backup_plist_sha256": _file_sha(base_plist),
        },
        "candidate": {
            "root": str(candidate_root),
            "app_root": str(candidate_app),
            "release_id": candidate_id,
            "manifest_path": str(manifest_path),
            "manifest_sha256": manifest_sha,
        },
        "phase_a_client_source_delta": owner_diff_records,
        "api_backend_and_stage_consumer_preserved": source_backend_consumer,
        "current_owner_inventory": {
            "owner_entry_count": len(base_entries),
            "owner_inventory_sha256": active["application_inventory_sha256"],
            "candidate_entry_count": len(app_inventory),
            "candidate_inventory_sha256": api_release.inventory_digest(app_inventory),
            "delta_entry_count": len(integration["delta_entries"]),
            "delta_entries": integration["delta_entries"],
            "non_delta_owner_entry_count": len(owner_non_delta),
            "non_delta_inventory_sha256": owner_preservation["owner_non_delta_inventory_sha256"],
            "candidate_non_delta_entry_count": len(candidate_non_delta),
            "candidate_non_delta_inventory_sha256": owner_preservation["candidate_non_delta_inventory_sha256"],
            "all_other_owner_bytes_exact": owner_preservation["all_other_current_v24_owner_bytes_exact"],
        },
        "canonical_frontend_graph": {
            "build_receipt_path": frontend_build["receipt_path"],
            "build_receipt_sha256": frontend_build["receipt_sha256"],
            "source_graph_sha256": frontend_build["source_graph_sha256"],
            "source_input_entry_count": frontend_build["source_input_entry_count"],
            "source_inputs": source_records,
            "source_vs_current_owner_comparison": graph_owner_comparison,
            "source_vs_owner_counts": {
                "same": sum(row["classification"] == "SAME_AS_CURRENT_OWNER_SOURCE" for row in graph_owner_comparison),
                "canonical_additions": sum(row["classification"] == "CANONICAL_GRAPH_ADDITION_TO_CURRENT_OWNER_SOURCE" for row in graph_owner_comparison),
                "canonical_differences": sum(row["classification"] == "CANONICAL_GRAPH_DIFFERS_FROM_CURRENT_OWNER_SOURCE" for row in graph_owner_comparison),
                "owner_only": sum(row["classification"] == "CURRENT_OWNER_SOURCE_NOT_IN_CANONICAL_GRAPH" for row in graph_owner_comparison),
            },
        },
        "frontend_assets": {
            "fresh_build_dist_inventory": frontend_build["fresh_build_dist_inventory"],
            "fresh_build_dist_inventory_sha256": frontend_build["fresh_build_dist_inventory_sha256"],
            "candidate_installed_dist_inventory": frontend_build["candidate_dist_inventory"],
            "candidate_installed_dist_inventory_sha256": frontend_build["candidate_dist_inventory_sha256"],
            "generated_delta_receipt": frontend_delta,
            "current_owner_unreferenced_dist_assets_preserved": True,
        },
        "owner_non_delta_preservation": owner_preservation,
        "activebase_verification": activebase_verification,
        "staged_plist_verification": staged_plist_verification,
        "candidate_only_testclient": runtime_smoke,
        "active_plist_changed": False,
        "launchctl_called": False,
        "API_UI_AND_NATURAL_SLOT": "CANNOT_CONFIRM",
        "build_receipt_path": str(builder_receipt),
        "delta_receipt_path": str(delta_path),
    }
    report_path = root / "api" / "api-stage-client-candidate-report-r8.json"
    _write_json(report_path, report)
    return {
        "candidate_status": "READY_FOR_REVIEW",
        "candidate_root": str(candidate_root),
        "candidate_manifest_path": str(manifest_path),
        "candidate_manifest_sha256": manifest_sha,
        "report": report,
        "report_path": str(report_path),
        "build_receipt": str(builder_receipt),
    }


def _sync_source_payload(batch: int, relative: str) -> bytes:
    path = BASE / f"BATCH{batch}_SYNC_FILES.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    matches = [row for row in rows if row.get("path") == relative]
    if len(matches) != 1:
        raise ValueError(f"expected one accepted Batch {batch} payload for {relative}")
    row = matches[0]
    raw = str(row["content"]).encode("utf-8")
    expected = str(row["sha256"])
    if _sha(raw) != expected or _file_sha(REPO_ROOT / relative) != expected:
        raise ValueError(f"accepted after-byte mismatch for Batch {batch} {relative}")
    return raw


def _pinned_sync_payload(batch: int, relative: str) -> tuple[bytes, dict[str, Any]]:
    pin = SCHEDULER_REBASE_SYNC_INPUTS[batch]
    receipt_path = Path(pin["receipt"])
    files_path = Path(pin["files"])
    if _file_sha(receipt_path) != pin["receipt_sha256"] or _file_sha(files_path) != pin["files_sha256"]:
        raise ValueError(f"Batch {batch} reviewed scheduler source receipt/bundle changed")
    receipt = _read_json(receipt_path)
    if receipt.get("REVIEWED") != "PASS" or receipt.get("BEHAVIOR_VERIFIED") != "PASS":
        raise ValueError(f"Batch {batch} source overlay does not have a reviewed behavior PASS")
    rows = receipt.get("files") if batch in {1, 3} else receipt.get("changed_paths")
    if not isinstance(rows, list):
        raise ValueError(f"Batch {batch} reviewed source inventory is invalid")
    matches = [row for row in rows if isinstance(row, dict) and row.get("path") == relative]
    if len(matches) != 1:
        raise ValueError(f"Batch {batch} reviewed source path is not unique: {relative}")
    receipt_row = matches[0]
    expected_sha = str(receipt_row.get("after_sha256") or "")
    payload_rows = json.loads(files_path.read_text(encoding="utf-8"))
    payload_matches = [row for row in payload_rows if isinstance(row, dict) and row.get("path") == relative]
    if len(payload_matches) != 1:
        raise ValueError(f"Batch {batch} source payload is not unique: {relative}")
    payload_row = payload_matches[0]
    raw = str(payload_row.get("content") or "").encode("utf-8")
    if (not expected_sha or payload_row.get("sha256") != expected_sha
            or _sha(raw) != expected_sha or _file_sha(REPO_ROOT / relative) != expected_sha):
        raise ValueError(f"Batch {batch} accepted source SHA mismatch: {relative}")
    return raw, {
        "source_kind": f"REVIEWED_BATCH{batch}_SYNC_BYTES",
        "source_path": str(files_path),
        "source_bundle_sha256": str(pin["files_sha256"]),
        "review_receipt_path": str(receipt_path),
        "review_receipt_sha256": str(pin["receipt_sha256"]),
        "reviewed_after_sha256": expected_sha,
    }


def _scheduler_rebase_source_payloads() -> tuple[dict[str, bytes], dict[str, dict[str, Any]]]:
    """Resolve only the frozen B1/B3/6A/6B runtime closure and nine modules."""
    payloads: dict[str, bytes] = {}
    origins: dict[str, dict[str, Any]] = {}

    def add(relative: str, raw: bytes, origin: Mapping[str, Any]) -> None:
        actual_sha = _sha(raw)
        if origin.get("reviewed_after_sha256") != actual_sha:
            raise ValueError(f"reviewed scheduler source origin SHA mismatch: {relative}")
        if relative in payloads:
            if _sha(payloads[relative]) != actual_sha:
                raise ValueError(f"conflicting reviewed scheduler source bytes: {relative}")
            merged = dict(origins[relative])
            previous = list(merged.get("additional_reviewed_origins") or [])
            previous.append(dict(origin))
            merged["additional_reviewed_origins"] = previous
            origins[relative] = merged
            return
        payloads[relative] = raw
        origins[relative] = dict(origin)

    for batch in (1, 3):
        for relative in SCHEDULER_BATCH_PATHS[batch]:
            raw, origin = _pinned_sync_payload(batch, relative)
            add(relative, raw, origin)

    batch6a = _read_json(SCHEDULER_REBASE_SYNC_INPUTS[6]["receipt"])
    if (_file_sha(Path(SCHEDULER_REBASE_SYNC_INPUTS[6]["receipt"]))
            != SCHEDULER_REBASE_SYNC_INPUTS[6]["receipt_sha256"]
            or _file_sha(Path(SCHEDULER_REBASE_SYNC_INPUTS[6]["files"]))
            != SCHEDULER_REBASE_SYNC_INPUTS[6]["files_sha256"]
            or batch6a.get("REVIEWED") != "PASS"
            or batch6a.get("BEHAVIOR_VERIFIED") != "PASS"):
        raise ValueError("Batch 6A reviewed source receipt/bundle identity mismatch")
    batch6a_rows = batch6a.get("changed_paths")
    batch6a_payload_rows = json.loads(
        Path(SCHEDULER_REBASE_SYNC_INPUTS[6]["files"]).read_text(encoding="utf-8")
    )
    if not isinstance(batch6a_rows, list):
        raise ValueError("Batch 6A reviewed source list is invalid")
    for relative, expected_sha in SCHEDULER_REBASE_PHASE6A_RUNTIME_SHA256.items():
        review_matches = [row for row in batch6a_rows if isinstance(row, dict) and row.get("path") == relative]
        payload_matches = [row for row in batch6a_payload_rows if isinstance(row, dict) and row.get("path") == relative]
        if len(review_matches) != 1 or len(payload_matches) != 1:
            raise ValueError(f"Batch 6A reviewed runtime source is missing or ambiguous: {relative}")
        review_row, payload_row = review_matches[0], payload_matches[0]
        raw = str(payload_row.get("content") or "").encode("utf-8")
        if (review_row.get("after_sha256") != expected_sha
                or payload_row.get("sha256") != expected_sha
                or _sha(raw) != expected_sha
                or _file_sha(REPO_ROOT / relative) != expected_sha):
            raise ValueError(f"Batch 6A reviewed runtime source SHA mismatch: {relative}")
        add(relative, raw, {
            "source_kind": "REVIEWED_BATCH6A_SYNC_BYTES",
            "source_path": str(SCHEDULER_REBASE_SYNC_INPUTS[6]["files"]),
            "source_bundle_sha256": SCHEDULER_REBASE_SYNC_INPUTS[6]["files_sha256"],
            "review_receipt_path": str(SCHEDULER_REBASE_SYNC_INPUTS[6]["receipt"]),
            "review_receipt_sha256": SCHEDULER_REBASE_SYNC_INPUTS[6]["receipt_sha256"],
            "reviewed_after_sha256": expected_sha,
        })

    if _file_sha(SCHEDULER_REBASE_PHASE6B_REVIEW) != SCHEDULER_REBASE_PHASE6B_REVIEW_SHA256:
        raise ValueError("Phase 6B independent review receipt changed")
    phase6b = _read_json(SCHEDULER_REBASE_PHASE6B_REVIEW)
    verdict = phase6b.get("verdict") or {}
    if (verdict.get("REVIEWED") != "PASS" or verdict.get("BEHAVIOR_VERIFIED")
            != "PASS_FOR_FROZEN_LOCAL_CANDIDATE_TARGET"):
        raise ValueError("Phase 6B runtime overlay lacks its frozen candidate review PASS")
    actual_files = (phase6b.get("actual_diff") or {}).get("files")
    if not isinstance(actual_files, list):
        raise ValueError("Phase 6B reviewed source diff inventory is invalid")
    for relative, expected_sha in SCHEDULER_REBASE_PHASE6B_RUNTIME_SHA256.items():
        matches = [row for row in actual_files if isinstance(row, dict) and row.get("path") == relative]
        if len(matches) != 1 or matches[0].get("after_sha256") != expected_sha:
            raise ValueError(f"Phase 6B reviewed runtime source row mismatch: {relative}")
        source_path = _relative_file(REPO_ROOT, relative)
        if _file_sha(source_path) != expected_sha:
            raise ValueError(f"Phase 6B reviewed runtime source SHA mismatch: {relative}")
        add(relative, source_path.read_bytes(), {
            "source_kind": "PHASE6B_INDEPENDENTLY_REVIEWED_RUNTIME_SOURCE",
            "source_path": str(source_path),
            "review_receipt_path": str(SCHEDULER_REBASE_PHASE6B_REVIEW),
            "review_receipt_sha256": SCHEDULER_REBASE_PHASE6B_REVIEW_SHA256,
            "reviewed_after_sha256": expected_sha,
        })

    if _file_sha(MODULE_CLOSURE) != SCHEDULER_REBASE_MODULE_CLOSURE_SHA256:
        raise ValueError("frozen nine-module scheduler source closure changed")
    module_closure = _read_json(MODULE_CLOSURE)
    module_rows = module_closure.get("candidate_dependency_additions")
    if not isinstance(module_rows, list):
        raise ValueError("frozen preselection module closure is invalid")
    module_by_path = {
        str(row.get("path")): row for row in module_rows
        if isinstance(row, dict) and isinstance(row.get("path"), str)
        and str(row.get("path")).startswith("domains/_preselection_parts/")
    }
    if (len(module_by_path) != len(SCHEDULER_REBASE_PRESELECTION_MODULE_SHA256)
            or set(module_by_path) != set(SCHEDULER_REBASE_PRESELECTION_MODULE_SHA256)):
        raise ValueError("frozen preselection module paths differ from the exact nine-module scope")
    for relative, expected_sha in SCHEDULER_REBASE_PRESELECTION_MODULE_SHA256.items():
        row = module_by_path[relative]
        if (row.get("source_sha256") != expected_sha
                or row.get("write_scope") != "CANDIDATE_ADDITION_ONLY_CANONICAL_READ_ONLY"):
            raise ValueError(f"frozen preselection module scope/hash mismatch: {relative}")
        snapshot = Path(str(row.get("snapshot") or ""))
        if not snapshot.is_absolute() or not snapshot.resolve().is_relative_to(BASE.resolve()):
            raise ValueError(f"frozen preselection module snapshot escaped the R8 receipt workspace: {relative}")
        if _file_sha(snapshot) != expected_sha or _file_sha(REPO_ROOT / relative) != expected_sha:
            raise ValueError(f"frozen preselection module source SHA mismatch: {relative}")
        add(relative, snapshot.read_bytes(), {
            "source_kind": "FROZEN_PHASE6B_PRESELECTION_CANDIDATE_ADDITION_PENDING_OWNER_REVIEW",
            "source_path": str(snapshot),
            "source_bundle_sha256": SCHEDULER_REBASE_MODULE_CLOSURE_SHA256,
            "reviewed_after_sha256": expected_sha,
        })

    stage_contract_path = REPO_ROOT / "ops/stage_service_overlay_contract.py"
    if _file_sha(stage_contract_path) != SCHEDULER_REBASE_STAGE_OVERLAY_CONTRACT_SHA256:
        raise ValueError("reviewed Stage overlay contract changed before Scheduler dependency closure")
    from ops import stage_service_overlay_contract as stage_overlay
    for relative, expected_sha in SCHEDULER_REBASE_STAGE_CLOSURE_SUPPORT_SHA256.items():
        if stage_overlay.STAGE_SERVICE_RELEASE_CLOSURE_SHA256.get(relative) != expected_sha:
            raise ValueError(f"reviewed Stage closure no longer pins required Scheduler dependency: {relative}")
        source_path = _relative_file(REPO_ROOT, relative)
        if _file_sha(source_path) != expected_sha:
            raise ValueError(f"reviewed Stage closure support source SHA mismatch: {relative}")
        add(relative, source_path.read_bytes(), {
            "source_kind": "PHASE6B_REVIEWED_STAGE_RELEASE_CLOSURE_SUPPORT",
            "source_path": str(source_path),
            "source_contract_path": str(stage_contract_path),
            "source_contract_sha256": SCHEDULER_REBASE_STAGE_OVERLAY_CONTRACT_SHA256,
            "review_receipt_path": str(SCHEDULER_REBASE_PHASE6B_REVIEW),
            "review_receipt_sha256": SCHEDULER_REBASE_PHASE6B_REVIEW_SHA256,
            "reviewed_after_sha256": expected_sha,
        })

    if (_file_sha(SCHEDULER_REBASE_LOCK_HELPER_SCOPE) != SCHEDULER_REBASE_LOCK_HELPER_SCOPE_SHA256
            or _file_sha(SCHEDULER_REBASE_LOCK_HELPER_IDENTITY) != SCHEDULER_REBASE_LOCK_HELPER_IDENTITY_SHA256
            or _file_sha(SCHEDULER_REBASE_LOCK_HELPER_DIFF) != SCHEDULER_REBASE_LOCK_HELPER_DIFF_SHA256):
        raise ValueError("Scheduler lock-helper dependency scope or origin evidence changed")
    scope = _read_json(SCHEDULER_REBASE_LOCK_HELPER_SCOPE)
    helper_relative, helper_sha = next(iter(SCHEDULER_REBASE_LOCK_HELPER_SHA256.items()))
    lock_addendum = scope.get("candidate_lock_helper_addendum") or {}
    if (lock_addendum.get("path") != helper_relative
            or lock_addendum.get("sha256") != helper_sha
            or lock_addendum.get("owner_before_sha256") != SCHEDULER_REBASE_LOCK_HELPER_OWNER_BEFORE_SHA256
            or lock_addendum.get("canonical_edit_allowed") is not False
            or lock_addendum.get("candidate_copy_allowed") is not True
            or lock_addendum.get("activation_allowed_before_focused_review") is not False
            or lock_addendum.get("identity_evidence") != str(SCHEDULER_REBASE_LOCK_HELPER_IDENTITY)
            or lock_addendum.get("diff_evidence") != str(SCHEDULER_REBASE_LOCK_HELPER_DIFF)):
        raise ValueError("Scheduler lock-helper candidate-only scope addendum changed")
    lock_identity_rows = json.loads(SCHEDULER_REBASE_LOCK_HELPER_IDENTITY.read_text(encoding="utf-8"))
    expected_lock_identity_shas = {
        "canonical": helper_sha,
        "current_scheduler": SCHEDULER_REBASE_LOCK_HELPER_OWNER_BEFORE_SHA256,
        "stage_owner": helper_sha,
        "api_candidate": helper_sha,
    }
    if (not isinstance(lock_identity_rows, list)
            or {row.get("root") for row in lock_identity_rows if isinstance(row, dict)}
            != set(expected_lock_identity_shas)
            or len(lock_identity_rows) != len(expected_lock_identity_shas)):
        raise ValueError("Scheduler lock-helper identity evidence root set changed")
    owner_identity = _read_json(SCHEDULER_OWNER_REBASE)
    owner_app = Path(str(owner_identity.get("root") or ""))
    if (_file_sha(SCHEDULER_OWNER_REBASE) != SCHEDULER_OWNER_REBASE_SHA256
            or owner_app != Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
                                 "research-workbench-simplification-scheduler-20261012-r2/app")):
        raise ValueError("Scheduler lock-helper evidence no longer binds the pinned current owner")
    expected_lock_identity_paths = {
        "canonical": REPO_ROOT / helper_relative,
        "current_scheduler": owner_app / helper_relative,
        "stage_owner": STAGE_BASELINE_APP / helper_relative,
        "api_candidate": OUTPUT_ROOT / "api" / "research-workbench-simplification-api-20261013-r8-candidate"
        / "app" / helper_relative,
    }
    for row in lock_identity_rows:
        root_name = str(row["root"])
        path = Path(str(row.get("path") or ""))
        expected_path = expected_lock_identity_paths[root_name]
        expected_sha = expected_lock_identity_shas[root_name]
        if (path != expected_path or row.get("sha256") != expected_sha
                or not path.is_file() or path.is_symlink() or _file_sha(path) != expected_sha):
            raise ValueError(f"Scheduler lock-helper origin identity mismatch for {root_name}")
        if row.get("bytes") != path.stat().st_size:
            raise ValueError(f"Scheduler lock-helper origin byte count mismatch for {root_name}")
    diff_text = SCHEDULER_REBASE_LOCK_HELPER_DIFF.read_text(encoding="utf-8")
    if not diff_text.startswith(
        "--- latest_scheduler_r2/infrastructure/interprocess_lock.py\n"
        "+++ pinned_existing/infrastructure/interprocess_lock.py\n"
    ):
        raise ValueError("Scheduler lock-helper diff evidence is not the pinned owner-to-helper comparison")
    helper_source_path = REPO_ROOT / helper_relative
    helper_source_bytes = helper_source_path.read_bytes()
    if _file_sha(helper_source_path) != helper_sha:
        raise ValueError("Scheduler lock-helper pinned source SHA mismatch")
    add(helper_relative, helper_source_bytes, {
        "source_kind": "EXACT_PINNED_EXISTING_SCHEDULER_LOCK_HELPER_CANDIDATE_ONLY",
        "source_path": str(helper_source_path),
        "owner_before_sha256": SCHEDULER_REBASE_LOCK_HELPER_OWNER_BEFORE_SHA256,
        "scope_addendum_path": str(SCHEDULER_REBASE_LOCK_HELPER_SCOPE),
        "scope_addendum_sha256": SCHEDULER_REBASE_LOCK_HELPER_SCOPE_SHA256,
        "origin_identity_path": str(SCHEDULER_REBASE_LOCK_HELPER_IDENTITY),
        "origin_identity_sha256": SCHEDULER_REBASE_LOCK_HELPER_IDENTITY_SHA256,
        "origin_diff_path": str(SCHEDULER_REBASE_LOCK_HELPER_DIFF),
        "origin_diff_sha256": SCHEDULER_REBASE_LOCK_HELPER_DIFF_SHA256,
        "independent_review_required": True,
        "reviewed_after_sha256": helper_sha,
    })

    if _file_sha(SCHEDULER_REBASE_IMPORT_CLOSURE_REPORT) != SCHEDULER_REBASE_IMPORT_CLOSURE_REPORT_SHA256:
        raise ValueError("Scheduler missing-import closure AST report changed")
    closure_report = _read_json(SCHEDULER_REBASE_IMPORT_CLOSURE_REPORT)
    closure_rows = closure_report.get("missing_pinned_import_closure")
    closure_addendum = scope.get("candidate_missing_import_closure_addendum") or {}
    scope_missing_pins = closure_addendum.get("allowed_missing_paths_exact_pins")
    if (closure_report.get("schema") != "r8.scheduler.missing_import_closure_ast.v3"
            or closure_report.get("owner_root") != str(owner_app)
            or closure_report.get("owner_identity_sha256") != SCHEDULER_OWNER_REBASE_SHA256
            or closure_report.get("scope_path") != str(SCHEDULER_REBASE_LOCK_HELPER_SCOPE)
            or closure_report.get("scope_sha256") != SCHEDULER_REBASE_LOCK_HELPER_SCOPE_SHA256
            or set(closure_report.get("seed_paths") or []) != set(SCHEDULER_REBASE_RUNTIME_OVERLAY_PATHS)
            | set(SCHEDULER_REBASE_PRESELECTION_MODULE_SHA256)
            | set(SCHEDULER_REBASE_OWNED_IO_SHA256)
            or closure_report.get("unresolved_local_imports") != []
            or not isinstance(closure_rows, list)
            or not isinstance(scope_missing_pins, dict)
            or {row.get("path"): row.get("sha256") for row in closure_rows if isinstance(row, dict)}
            != SCHEDULER_REBASE_MISSING_IMPORT_CLOSURE_SHA256
            or any(row.get("owner_absent") is not True
                   or not isinstance(row.get("imported_by_chains"), list)
                   or not row.get("imported_by_chains")
                   for row in closure_rows if isinstance(row, dict))):
        raise ValueError("Scheduler missing-import closure report does not bind the exact R2 owner/import paths")
    if any(scope_missing_pins.get(relative) != expected_sha
           for relative, expected_sha in SCHEDULER_REBASE_MISSING_IMPORT_CLOSURE_SHA256.items()):
        raise ValueError("Scheduler missing-import closure paths differ from the authorized exact pins")
    if (closure_addendum.get("canonical_edit_allowed") is not False
            or closure_addendum.get("existing_scheduler_path_replacement_allowed") is not False
            or closure_addendum.get("scope_gate_explicit")
            != SCHEDULER_REBASE_MISSING_IMPORT_CLOSURE_SHA256.get("infrastructure/scope_gate.py")):
        raise ValueError("Scheduler missing-import closure candidate-only boundaries changed")
    from ops import stage_service_overlay_contract as stage_overlay
    for relative, expected_sha in SCHEDULER_REBASE_MISSING_IMPORT_CLOSURE_SHA256.items():
        if stage_overlay.STAGE_SERVICE_RELEASE_CLOSURE_SHA256.get(relative) != expected_sha:
            raise ValueError(f"reviewed Stage closure no longer pins missing Scheduler import: {relative}")
        if any((owner_app / relative).exists() for owner_app in (
                Path(str(owner_identity.get("root") or "")),
                Path(str(owner_identity.get("root") or "")) / "upstreams")):
            raise ValueError(f"Scheduler owner is no longer missing the pinned import path: {relative}")
        source_path = _relative_file(REPO_ROOT, relative)
        if _file_sha(source_path) != expected_sha:
            raise ValueError(f"Scheduler missing-import pinned source SHA mismatch: {relative}")
        row = next(row for row in closure_rows if row.get("path") == relative)
        add(relative, source_path.read_bytes(), {
            "source_kind": "EXACT_PINNED_STAGE_IMPORT_CLOSURE_CANDIDATE_ONLY",
            "source_path": str(source_path),
            "owner_root": str(owner_identity.get("root") or ""),
            "owner_path_absent": True,
            "scope_addendum_path": str(SCHEDULER_REBASE_LOCK_HELPER_SCOPE),
            "scope_addendum_sha256": SCHEDULER_REBASE_LOCK_HELPER_SCOPE_SHA256,
            "scope_exact_sha256": expected_sha,
            "reviewed_stage_contract_path": str(REPO_ROOT / "ops/stage_service_overlay_contract.py"),
            "reviewed_stage_contract_sha256": SCHEDULER_REBASE_STAGE_OVERLAY_CONTRACT_SHA256,
            "import_closure_report_path": str(SCHEDULER_REBASE_IMPORT_CLOSURE_REPORT),
            "import_closure_report_sha256": SCHEDULER_REBASE_IMPORT_CLOSURE_REPORT_SHA256,
            "imported_by_chains": row["imported_by_chains"],
            "independent_review_required": True,
            "reviewed_after_sha256": expected_sha,
        })

    owned_io_relative, owned_io_sha = next(iter(SCHEDULER_REBASE_OWNED_IO_SHA256.items()))
    owned_io_addendum = scope.get("candidate_owned_io_pair_addendum") or {}
    if (owned_io_addendum.get("path") != owned_io_relative
            or owned_io_addendum.get("sha256") != owned_io_sha
            or owned_io_addendum.get("owner_before_sha256") != SCHEDULER_REBASE_OWNED_IO_OWNER_BEFORE_SHA256
            or owned_io_addendum.get("canonical_edit_allowed") is not False
            or owned_io_addendum.get("candidate_copy_allowed") is not True
            or owned_io_addendum.get("activation_allowed_before_focused_review") is not False
            or owned_io_addendum.get("identity_evidence") != str(SCHEDULER_REBASE_OWNED_IO_IDENTITY)
            or owned_io_addendum.get("diff_evidence") != str(SCHEDULER_REBASE_OWNED_IO_DIFF)
            or _file_sha(SCHEDULER_REBASE_OWNED_IO_IDENTITY) != SCHEDULER_REBASE_OWNED_IO_IDENTITY_SHA256
            or _file_sha(SCHEDULER_REBASE_OWNED_IO_DIFF) != SCHEDULER_REBASE_OWNED_IO_DIFF_SHA256):
        raise ValueError("Scheduler SafeRoot paired-dependency candidate-only scope/evidence changed")
    owner_identity_rows = json.loads(SCHEDULER_REBASE_OWNED_IO_IDENTITY.read_text(encoding="utf-8"))
    expected_owned_io_identities = {
        "canonical": (REPO_ROOT / owned_io_relative, owned_io_sha),
        "scheduler": (owner_app / owned_io_relative, SCHEDULER_REBASE_OWNED_IO_OWNER_BEFORE_SHA256),
        "stage": (STAGE_BASELINE_APP / owned_io_relative, owned_io_sha),
        "api": (OUTPUT_ROOT / "api" / "research-workbench-simplification-api-20261013-r8-candidate"
                / "app" / owned_io_relative, owned_io_sha),
    }
    if (not isinstance(owner_identity_rows, list)
            or {row.get("root") for row in owner_identity_rows if isinstance(row, dict)}
            != set(expected_owned_io_identities)
            or len(owner_identity_rows) != len(expected_owned_io_identities)):
        raise ValueError("Scheduler SafeRoot pair origin identity root set changed")
    for row in owner_identity_rows:
        root_name = str(row["root"])
        path = Path(str(row.get("path") or ""))
        expected_path, expected_sha = expected_owned_io_identities[root_name]
        if (path != expected_path or row.get("sha256") != expected_sha
                or not path.is_file() or path.is_symlink() or _file_sha(path) != expected_sha
                or row.get("bytes") != path.stat().st_size):
            raise ValueError(f"Scheduler SafeRoot paired-dependency origin identity mismatch for {root_name}")
    owned_io_diff_text = SCHEDULER_REBASE_OWNED_IO_DIFF.read_text(encoding="utf-8")
    if not owned_io_diff_text.startswith(
        "--- latest_scheduler_r2/infrastructure/owned_io.py\n"
        "+++ existing_stage_api_pinned/infrastructure/owned_io.py\n"
    ):
        raise ValueError("Scheduler SafeRoot pair diff evidence is not the exact owner-to-pinned comparison")
    owned_io_source_path = REPO_ROOT / owned_io_relative
    if _file_sha(owned_io_source_path) != owned_io_sha:
        raise ValueError("Scheduler SafeRoot paired-dependency pinned source SHA mismatch")
    add(owned_io_relative, owned_io_source_path.read_bytes(), {
        "source_kind": "EXACT_PINNED_EXISTING_STAGE_API_SAFEROOT_PAIR_CANDIDATE_ONLY",
        "source_path": str(owned_io_source_path),
        "owner_before_sha256": SCHEDULER_REBASE_OWNED_IO_OWNER_BEFORE_SHA256,
        "scope_addendum_path": str(SCHEDULER_REBASE_LOCK_HELPER_SCOPE),
        "scope_addendum_sha256": SCHEDULER_REBASE_LOCK_HELPER_SCOPE_SHA256,
        "origin_identity_path": str(SCHEDULER_REBASE_OWNED_IO_IDENTITY),
        "origin_identity_sha256": SCHEDULER_REBASE_OWNED_IO_IDENTITY_SHA256,
        "origin_diff_path": str(SCHEDULER_REBASE_OWNED_IO_DIFF),
        "origin_diff_sha256": SCHEDULER_REBASE_OWNED_IO_DIFF_SHA256,
        "kernel_lock_yields_owned_fd": True,
        "paired_lock_helper_path": next(iter(SCHEDULER_REBASE_LOCK_HELPER_SHA256)),
        "paired_lock_helper_sha256": next(iter(SCHEDULER_REBASE_LOCK_HELPER_SHA256.values())),
        "independent_review_required": True,
        "reviewed_after_sha256": owned_io_sha,
    })

    expected_paths = {
        *SCHEDULER_REBASE_RUNTIME_OVERLAY_PATHS,
        *SCHEDULER_REBASE_PRESELECTION_MODULE_SHA256,
        *SCHEDULER_REBASE_MISSING_IMPORT_CLOSURE_SHA256,
        *SCHEDULER_REBASE_OWNED_IO_SHA256,
    }
    if set(payloads) != expected_paths:
        raise ValueError("scheduler reviewed runtime source closure changed from its frozen exact path set")
    return payloads, origins


def _validate_scheduler_owner_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    if identity.get("status") != "LATEST_OWNER_FROZEN_NO_REPLACEMENT":
        raise ValueError("current scheduler owner receipt status is not frozen for candidate rebasing")
    root = Path(str(identity.get("root") or ""))
    manifest_path = Path(str(identity.get("manifest_path") or ""))
    plist_path = Path(str(identity.get("plist_path") or ""))
    backup_path = Path(str(identity.get("backup") or ""))
    if (not root.is_absolute() or root.is_symlink() or not root.is_dir()
            or manifest_path != root.parent / "release-manifest.json"
            or not manifest_path.is_file() or manifest_path.is_symlink()
            or not plist_path.is_file() or plist_path.is_symlink()
            or not backup_path.is_file() or backup_path.is_symlink()):
        raise ValueError("current scheduler owner root/manifest/plist binding is invalid")
    if (identity.get("manifest_sha256") != SCHEDULER_OWNER_REBASE_MANIFEST_SHA256
            or _file_sha(manifest_path) != SCHEDULER_OWNER_REBASE_MANIFEST_SHA256
            or identity.get("plist_sha256") != SCHEDULER_OWNER_REBASE_PLIST_SHA256
            or _file_sha(plist_path) != SCHEDULER_OWNER_REBASE_PLIST_SHA256
            or _file_sha(backup_path) != SCHEDULER_OWNER_REBASE_PLIST_SHA256):
        raise ValueError("current scheduler owner manifest or matching live/backup plist changed")
    manifest = _read_json(manifest_path)
    candidate = manifest.get("candidate") or {}
    safe_identity = identity.get("safe_identity_env") or {}
    plist = plistlib.loads(plist_path.read_bytes())
    env = plist.get("EnvironmentVariables") or {}
    release_id = str(safe_identity.get("V35_RELEASE_ID") or "")
    if (not release_id or candidate.get("release_id") != release_id
            or candidate.get("root") != str(root.parent)
            or candidate.get("app_root") != str(root)
            or safe_identity.get("V35_APP_ROOT") != str(root)
            or safe_identity.get("V35_RELEASE_MANIFEST_PATH") != str(manifest_path)
            or safe_identity.get("V35_RELEASE_MANIFEST_SHA256") != SCHEDULER_OWNER_REBASE_MANIFEST_SHA256):
        raise ValueError("current scheduler owner release identity differs from its frozen manifest")
    for key, value in safe_identity.items():
        if env.get(key) != value:
            raise ValueError(f"current scheduler plist safe identity binding mismatch: {key}")
    arguments = plist.get("ProgramArguments")
    if (not isinstance(arguments, list) or len(arguments) != 2
            or arguments[0] != "/bin/bash"
            or Path(str(arguments[1])) != root / "ops/launch_v35_macos_scheduler.sh"
            or plist.get("WorkingDirectory") != str(root)):
        raise ValueError("current scheduler plist does not launch from the exact frozen owner app")
    inventory = manifest.get("application_inventory") or {}
    actual_inventory = __import__("ops.api_release_integration", fromlist=["inventory_tree"]).inventory_tree(root)
    declared_count = inventory.get("entry_count")
    if (actual_inventory != inventory.get("entries")
            or (declared_count is not None and declared_count != len(actual_inventory))):
        raise ValueError("current scheduler owner inventory differs from its exact release manifest")
    for row in identity.get("source_identities", []):
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ValueError("current scheduler source identity row is malformed")
        path = _relative_file(root, str(row["path"]))
        expected = row.get("owner_sha256")
        if expected is None:
            if path.exists():
                raise ValueError(f"frozen scheduler owner expected a missing target path: {row['path']}")
        elif not path.is_file() or _file_sha(path) != expected:
            raise ValueError(f"frozen scheduler owner source identity mismatch: {row['path']}")
    return {
        "root": root,
        "manifest_path": manifest_path,
        "manifest": manifest,
        "plist_path": plist_path,
        "backup_path": backup_path,
        "plist": plist,
        "release_id": release_id,
        "application_inventory": actual_inventory,
        "manifest_sha256": SCHEDULER_OWNER_REBASE_MANIFEST_SHA256,
        "plist_sha256": SCHEDULER_OWNER_REBASE_PLIST_SHA256,
    }


def _verify_scheduler_identity_render(
    *, source_plist: Mapping[str, Any], candidate_plist: Mapping[str, Any],
    owner_app: Path, candidate_root: Path, release_id: str,
    manifest_path: Path, manifest_sha256: str,
) -> dict[str, Any]:
    source_env = source_plist.get("EnvironmentVariables") or {}
    candidate_env = candidate_plist.get("EnvironmentVariables") or {}
    candidate_app = candidate_root / "app"
    expected_pythonpath = str(source_env.get("PYTHONPATH") or "")
    if (expected_pythonpath.count(str(owner_app)) != 2
            or expected_pythonpath != str(owner_app / "upstreams") + os.pathsep + str(owner_app)):
        raise ValueError("scheduler PYTHONPATH is not the exact owner upstream/app binding")
    expected_env: dict[str, Any] = {}
    for key, value in source_env.items():
        if key == "PYTHONPATH":
            expected_env[key] = expected_pythonpath.replace(str(owner_app), str(candidate_app))
        elif isinstance(value, str) and Path(value).is_absolute():
            try:
                suffix = Path(value).relative_to(owner_app)
            except ValueError:
                expected_env[key] = value
            else:
                expected_env[key] = str(candidate_app / suffix)
        else:
            expected_env[key] = value
    expected_env.update({
        "V35_APP_ROOT": str(candidate_app),
        "V35_RELEASE_ID": release_id,
        "V35_RELEASE_MANIFEST_PATH": str(manifest_path),
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha256,
    })
    if candidate_env != expected_env:
        changed = sorted(key for key in set(candidate_env) | set(expected_env)
                         if candidate_env.get(key) != expected_env.get(key))
        raise ValueError("staged scheduler environment changed outside the exact owner-root identity render: "
                         + ",".join(changed))
    if candidate_env.get("PYTHONPATH") != expected_pythonpath.replace(str(owner_app), str(candidate_app)):
        raise ValueError("staged scheduler PYTHONPATH did not receive exact owner-root substitution")
    if (candidate_plist.get("ProgramArguments")
            != ["/bin/bash", str(candidate_app / "ops/launch_v35_macos_scheduler.sh")]
            or candidate_plist.get("WorkingDirectory") != str(candidate_app)):
        raise ValueError("staged scheduler launcher identity does not point to the candidate app")
    for key in SCHEDULER_IDENTITY_SCHEDULE_FIELDS:
        if source_plist.get(key) != candidate_plist.get(key):
            raise ValueError(f"staged scheduler schedule field changed: {key}")
    if any(source_env.get(key) != candidate_env.get(key)
           for key in SCHEDULER_IDENTITY_EXTERNAL_ROOT_FIELDS):
        raise ValueError("staged scheduler external data roots changed")
    return {
        "status": "PASS",
        "exact_owner_root_pythonpath_replacement": True,
        "owner_pythonpath": source_env["PYTHONPATH"],
        "candidate_pythonpath": candidate_env["PYTHONPATH"],
        "only_identity_environment_fields_rebased": True,
        "external_environment_bindings_preserved": True,
        "schedule_fields_preserved": {key: candidate_plist.get(key) for key in SCHEDULER_IDENTITY_SCHEDULE_FIELDS},
    }


def _run_scheduler_candidate_import_canary(
    *, root: Path, candidate_app: Path, module_paths: list[str],
    expected_inventory: list[dict[str, Any]], runtime_root: Path,
) -> dict[str, Any]:
    sys.path.insert(0, str(REPO_ROOT))
    from ops import api_release_integration as api_release

    module_names = sorted({
        ".".join(Path(relative).with_suffix("").parts[:-1] + (() if Path(relative).name == "__init__.py" else (Path(relative).stem,)))
        for relative in module_paths
        if relative.endswith(".py")
    })
    probe_path = root / "scheduler" / "candidate_import_origin_probe.py"
    origins_path = root / "scheduler" / "candidate_import_origins.json"
    code = '''from __future__ import annotations
import importlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
modules = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
rows = []
for name in modules:
    module = importlib.import_module(name)
    origin_value = getattr(module, "__file__", None)
    if not origin_value:
        raise RuntimeError(f"module has no concrete file origin: {name}")
    origin = pathlib.Path(origin_value).resolve()
    if not origin.is_relative_to(root):
        raise RuntimeError(f"module resolved outside candidate app: {name}: {origin}")
    rows.append({"module": name, "origin": str(origin)})
print(json.dumps({"status": "PASS", "candidate_app": str(root), "module_origins": rows}, sort_keys=True))
'''
    with probe_path.open("x", encoding="utf-8") as handle:
        handle.write(code)
    with origins_path.open("x", encoding="utf-8") as handle:
        json.dump(module_names, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    python_executable = runtime_root / "venvs" / "v3.5-mac" / "bin" / "python"
    if not runtime_root.is_dir() or not python_executable.is_file() or not os.access(python_executable, os.X_OK):
        raise ValueError("scheduler candidate import canary cannot resolve the owner-bound runtime Python")
    version_command = [
        str(python_executable), "-S", "-c",
        "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
    ]
    version_probe = subprocess.run(
        version_command, cwd=candidate_app, env=environment,
        capture_output=True, text=True, check=False,
    )
    runtime_version = version_probe.stdout.strip()
    if version_probe.returncode != 0 or not re.fullmatch(r"\d+\.\d+", runtime_version):
        raise RuntimeError("owner-bound scheduler runtime Python version probe failed")
    site_packages = runtime_root / "venvs" / "v3.5-mac" / "lib" / f"python{runtime_version}" / "site-packages"
    if not site_packages.is_dir():
        raise ValueError("owner-bound scheduler runtime site-packages directory is missing")
    # Match launch_v35_macos_scheduler.sh: candidate app, runtime site-packages,
    # then the plist's candidate upstream/app entries, with bytecode writes off.
    environment["PYTHONPATH"] = os.pathsep.join((
        str(candidate_app), str(site_packages), str(candidate_app / "upstreams"), str(candidate_app),
    ))
    command = [str(python_executable), "-S", str(probe_path), str(candidate_app), str(origins_path)]
    completed = subprocess.run(command, cwd=candidate_app, env=environment,
                               capture_output=True, text=True, check=False)
    log_path = root / "logs" / "scheduler_candidate_import_origin_canary.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("x", encoding="utf-8") as handle:
        handle.write("SCHEDULER_RUNTIME_PYTHON: " + str(python_executable) + "\n")
        handle.write("SCHEDULER_RUNTIME_PYTHON_VERSION: " + runtime_version + "\n")
        handle.write("SCHEDULER_RUNTIME_SITE_PACKAGES: " + str(site_packages) + "\n")
        handle.write("VERSION_PROBE_COMMAND: " + json.dumps(version_command, ensure_ascii=False) + "\n")
        handle.write("VERSION_PROBE_RETURN_CODE: " + str(version_probe.returncode) + "\n")
        handle.write("COMMAND: " + json.dumps(command, ensure_ascii=False) + "\n")
        handle.write("RETURN_CODE: " + str(completed.returncode) + "\n")
        handle.write("STDOUT:\n" + completed.stdout)
        handle.write("STDERR:\n" + completed.stderr)
    if completed.returncode != 0:
        raise RuntimeError(f"scheduler candidate import-origin canary failed; see {log_path}")
    payload = json.loads(completed.stdout)
    if payload.get("status") != "PASS" or len(payload.get("module_origins") or []) != len(module_names):
        raise ValueError("scheduler candidate import-origin canary result is incomplete")
    after_inventory = api_release.inventory_tree(candidate_app)
    if after_inventory != expected_inventory:
        raise ValueError("scheduler import-origin canary changed candidate app inventory")
    return {
        "status": "PASS",
        "module_count": len(module_names),
        "modules": payload["module_origins"],
        "candidate_app": str(candidate_app),
        "runtime_python": str(python_executable),
        "runtime_python_version": runtime_version,
        "runtime_site_packages": str(site_packages),
        "log_path": str(log_path),
        "log_sha256": _file_sha(log_path),
        "candidate_inventory_unchanged": True,
        "pycache_writes_disabled": True,
        "service_or_external_data_action": False,
    }


def _prepare_scheduler_owner_rebase(output_root: Path) -> dict[str, Any]:
    """Build an inactive Scheduler candidate from the exact current R2 owner."""
    resolved_output = output_root.resolve()
    candidates_root = (BASE / "candidates").resolve()
    if (not resolved_output.is_relative_to(candidates_root)
            or resolved_output == candidates_root
            or resolved_output.exists()):
        raise ValueError("scheduler rebase output must be a new isolated candidate directory under the R8 workspace")
    if _file_sha(SCHEDULER_OWNER_REBASE) != SCHEDULER_OWNER_REBASE_SHA256:
        raise ValueError("current Scheduler owner identity receipt changed")
    identity = _read_json(SCHEDULER_OWNER_REBASE)
    owner = _validate_scheduler_owner_identity(identity)
    source_payloads, source_origins = _scheduler_rebase_source_payloads()

    sys.path.insert(0, str(REPO_ROOT))
    from ops import api_release_integration as api_release
    from ops import build_release_candidate as builder

    owner_app = Path(owner["root"])
    owner_manifest = owner["manifest"]
    baseline_inventory = owner["application_inventory"]
    candidate_id = SCHEDULER_REBASE_RELEASE_ID
    candidate_root = resolved_output / "scheduler" / candidate_id
    candidate_app = candidate_root / "app"
    diff_root = resolved_output / "owner-base-diffs" / "scheduler"
    candidate_root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(owner_app, candidate_app, symlinks=True)
    if api_release.inventory_tree(candidate_app) != baseline_inventory:
        raise ValueError("latest Scheduler owner candidate copy inventory mismatch")

    source_records: list[dict[str, Any]] = []
    delta_records: list[dict[str, Any]] = []
    for relative in sorted(source_payloads):
        raw = source_payloads[relative]
        expected_sha = _sha(raw)
        record = _owner_entry(
            owner_app=owner_app,
            relative=relative,
            after=raw,
            after_sha=expected_sha,
            diff_root=diff_root,
            source_kind=str(source_origins[relative]["source_kind"]),
        )
        record["source_provenance"] = source_origins[relative]
        source_records.append(record)
        if record["classification"] != "SAME_ALREADY_PRESENT":
            delta_records.append(record)

    for record in delta_records:
        relative = str(record["path"])
        if (not relative or Path(relative).is_absolute()
                or ".." in Path(relative).parts):
            raise ValueError(f"unsafe scheduler overlay path: {relative}")
        target = _relative_file(candidate_app, relative)
        for parent in target.parents:
            if parent == candidate_app.parent:
                break
            if parent == candidate_app:
                continue
            if parent.is_symlink():
                raise ValueError(f"scheduler overlay parent traverses a symlink: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = source_payloads[relative]
        if target.exists():
            target.chmod(stat.S_IMODE(target.stat().st_mode) | stat.S_IWUSR)
            target.write_bytes(raw)
        else:
            with target.open("xb") as handle:
                handle.write(raw)
        shutil.copystat(REPO_ROOT / relative, target, follow_symlinks=False)
        if _file_sha(target) != record["after_sha256"]:
            raise ValueError(f"Scheduler candidate source overlay SHA mismatch: {relative}")

    candidate_inventory = api_release.inventory_tree(candidate_app)
    baseline_by_path = {str(row["path"]): row for row in baseline_inventory}
    candidate_by_path = {str(row["path"]): row for row in candidate_inventory}
    changed_paths = {str(row["path"]) for row in delta_records}
    removed = sorted(set(baseline_by_path) - set(candidate_by_path))
    unexpected_added = sorted((set(candidate_by_path) - set(baseline_by_path)) - changed_paths)
    unexpected_altered = sorted(
        path for path in set(baseline_by_path) & set(candidate_by_path)
        if path not in changed_paths and baseline_by_path[path] != candidate_by_path[path]
    )
    if removed or unexpected_added or unexpected_altered:
        raise ValueError(
            "Scheduler rebase contains owner changes outside the exact reviewed overlay paths: "
            f"removed={removed} added={unexpected_added} altered={unexpected_altered}"
        )
    non_delta_owner = [baseline_by_path[path] for path in sorted(baseline_by_path) if path not in changed_paths]
    non_delta_candidate = [candidate_by_path[path] for path in sorted(baseline_by_path) if path not in changed_paths]
    if non_delta_owner != non_delta_candidate:
        raise ValueError("latest Scheduler owner non-delta bytes were not preserved")
    changed_inventory = [candidate_by_path[path] for path in sorted(changed_paths)]

    candidate_manifest_path = candidate_root / "release-manifest.json"
    module_contract = candidate_app / "deployment" / "api_module_contracts.json"
    module_contract_sha = _file_sha(module_contract) if module_contract.is_file() else None
    candidate_manifest = {
        "schema_version": "v4.release_candidate.v1",
        "candidate_status": "READY_FOR_REVIEW",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "owner": "com.lexi.v35.scheduler",
        "baseline": {
            "release_id": owner["release_id"],
            "release_root": str(owner_app.parent),
            "app_root": str(owner_app),
            "manifest_path": str(owner["manifest_path"]),
            "manifest_sha256": owner["manifest_sha256"],
            "owner_identity_path": str(SCHEDULER_OWNER_REBASE),
            "owner_identity_sha256": SCHEDULER_OWNER_REBASE_SHA256,
            "plist_path": str(owner["plist_path"]),
            "plist_sha256": owner["plist_sha256"],
            "plist_backup_path": str(owner["backup_path"]),
            "plist_backup_sha256": owner["plist_sha256"],
        },
        "candidate": {
            "release_id": candidate_id,
            "root": str(candidate_root),
            "app_root": str(candidate_app),
            "module_role": "gateway",
            "module_contract_sha256": module_contract_sha,
            "formal_release_root": str(owner_app.parent.parent),
            "data_copy_performed": False,
            "runtime_venv_copied": False,
            "ignored_runtime_data_copied": False,
        },
        "reviewed_owner_deltas": delta_records,
        "source_diffs": source_records,
        "application_inventory": {
            "entry_count": len(candidate_inventory),
            "aggregate_sha256": api_release.inventory_digest(candidate_inventory),
            "entries": candidate_inventory,
        },
        "non_delta_owner_bytes_preserved": True,
        "non_delta_path_count": len(non_delta_owner),
        "non_delta_inventory_sha256": api_release.inventory_digest(non_delta_owner),
        "changed_path_inventory_sha256": api_release.inventory_digest(changed_inventory),
        "scheduler_workload_bytes_preserved": (
            baseline_by_path.get("contracts/runtime_workloads.json")
            == candidate_by_path.get("contracts/runtime_workloads.json")
        ),
        "candidate_addition_module_count": len(SCHEDULER_REBASE_PRESELECTION_MODULE_SHA256),
        "candidate_addition_modules_require_independent_review": True,
        "candidate_dependency_addition_path_count": len(SCHEDULER_REBASE_CANDIDATE_ADDITION_SHA256),
        "candidate_dependency_addition_sha256": SCHEDULER_REBASE_CANDIDATE_ADDITION_SHA256,
        "candidate_dependency_addition_requires_independent_review": True,
        "data_copy_performed": False,
    }
    _write_scheduler_manifest(candidate_manifest_path, candidate_manifest)
    identity_render = builder._stage_scheduler_identity(
        source_plist=Path(owner["backup_path"]),
        candidate_root=candidate_root,
        release_id=candidate_id,
        manifest_path=candidate_manifest_path,
        manifest_sha256=_file_sha(candidate_manifest_path),
    )
    original_plist = plistlib.loads(Path(owner["backup_path"]).read_bytes())
    candidate_plist = plistlib.loads(Path(identity_render["path"]).read_bytes())
    identity_proof = _verify_scheduler_identity_render(
        source_plist=original_plist,
        candidate_plist=candidate_plist,
        owner_app=owner_app,
        candidate_root=candidate_root,
        release_id=candidate_id,
        manifest_path=candidate_manifest_path,
        manifest_sha256=_file_sha(candidate_manifest_path),
    )
    import_canary = _run_scheduler_candidate_import_canary(
        root=resolved_output,
        candidate_app=candidate_app,
        module_paths=sorted(source_payloads),
        expected_inventory=candidate_inventory,
        runtime_root=Path(str(candidate_plist.get("EnvironmentVariables", {}).get(
            "V35_RUNTIME_ROOT", candidate_root / "runtime"
        ))),
    )
    report = {
        "schema_version": "r8.scheduler_owner_rebase_candidate.v1",
        "candidate_status": "READY_FOR_INDEPENDENT_REVIEW",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "owner_identity_receipt": {
            "path": str(SCHEDULER_OWNER_REBASE),
            "sha256": SCHEDULER_OWNER_REBASE_SHA256,
            "owner_root": str(owner_app),
            "release_id": owner["release_id"],
            "manifest_path": str(owner["manifest_path"]),
            "manifest_sha256": owner["manifest_sha256"],
            "live_plist_path": str(owner["plist_path"]),
            "live_plist_sha256": owner["plist_sha256"],
            "matching_backup_path": str(owner["backup_path"]),
            "matching_backup_sha256": owner["plist_sha256"],
        },
        "candidate_manifest": str(candidate_manifest_path),
        "candidate_manifest_sha256": _file_sha(candidate_manifest_path),
        "candidate_root": str(candidate_root),
        "candidate_app": str(candidate_app),
        "candidate_inventory_entry_count": len(candidate_inventory),
        "candidate_inventory_sha256": api_release.inventory_digest(candidate_inventory),
        "candidate_import_origin_canary": import_canary,
        "source_overlay_path_count": len(source_records),
        "source_overlay_delta_count": len(delta_records),
        "candidate_addition_module_count": len(SCHEDULER_REBASE_PRESELECTION_MODULE_SHA256),
        "candidate_dependency_addition_path_count": len(SCHEDULER_REBASE_CANDIDATE_ADDITION_SHA256),
        "candidate_dependency_addition_paths": sorted(SCHEDULER_REBASE_CANDIDATE_ADDITION_SHA256),
        "candidate_dependency_addition_sha256": SCHEDULER_REBASE_CANDIDATE_ADDITION_SHA256,
        "candidate_dependency_addition_requires_independent_review": True,
        "source_diffs": source_records,
        "non_delta_owner_bytes_preserved": True,
        "non_delta_path_count": len(non_delta_owner),
        "non_delta_inventory_sha256": api_release.inventory_digest(non_delta_owner),
        "scheduler_workload_bytes_preserved": candidate_manifest["scheduler_workload_bytes_preserved"],
        "staged_plist": identity_render,
        "staged_plist_identity_proof": identity_proof,
        "calendar_slots_preserved": original_plist.get("StartCalendarInterval") == candidate_plist.get("StartCalendarInterval"),
        "run_at_load_preserved": original_plist.get("RunAtLoad") == candidate_plist.get("RunAtLoad"),
        "schedule_fields_preserved": {key: candidate_plist.get(key) for key in SCHEDULER_IDENTITY_SCHEDULE_FIELDS},
        "external_roots_preserved": {key: candidate_plist["EnvironmentVariables"].get(key)
                                     for key in SCHEDULER_IDENTITY_EXTERNAL_ROOT_FIELDS},
        "forbidden_actions_performed": [],
    }
    report_path = resolved_output / "scheduler" / "scheduler-owner-rebase-candidate-report-r8.json"
    _write_json(report_path, report)
    return {"candidate_status": report["candidate_status"], "report": report, "report_path": str(report_path)}


def _write_scheduler_manifest(path: Path, value: Mapping[str, Any]) -> None:
    _write_json(path, value)


def _prepare_scheduler(root: Path) -> dict[str, Any]:
    sys.path.insert(0, str(REPO_ROOT))
    from ops import api_release_integration as api_release
    from ops import build_release_candidate as builder

    runtime = _read_json(RUNTIME_IDENTITY)
    service = runtime["services"]["com.lexi.v35.scheduler"]
    if service["plist_sha256"] != SCHEDULER_BACKUP_PLIST_SHA:
        raise ValueError("scheduler owner plist receipt SHA mismatch")
    if service["selected_roots_and_release"]["V35_RELEASE_ID"] != "research-hourly-empty-20261012-r4":
        raise ValueError("scheduler R4 owner release identity mismatch")
    if _file_sha(SCHEDULER_PLIST_BACKUP) != SCHEDULER_BACKUP_PLIST_SHA:
        raise ValueError("scheduler immutable plist backup hash mismatch")
    manifest_path = Path(service["selected_roots_and_release"]["V35_RELEASE_MANIFEST_PATH"])
    if _file_sha(manifest_path) != SCHEDULER_BASELINE_MANIFEST_SHA:
        raise ValueError("scheduler owner manifest SHA mismatch")
    manifest = _read_json(manifest_path)
    candidate = manifest.get("candidate", {})
    if candidate.get("release_id") != "research-hourly-empty-20261012-r4":
        raise ValueError("scheduler R4 manifest release identity mismatch")
    baseline_inventory = api_release.inventory_tree(SCHEDULER_BASELINE_APP)
    if baseline_inventory != manifest["application_inventory"]["entries"]:
        raise ValueError("scheduler active app inventory differs from its pinned manifest")

    source_payloads: dict[str, bytes] = {}
    for batch, relatives in SCHEDULER_BATCH_PATHS.items():
        for relative in relatives:
            source_payloads[relative] = _sync_source_payload(batch, relative)
    diff_root = root / "owner-base-diffs" / "scheduler"
    owner_records = []
    delta_records = []
    for relative in sorted(source_payloads):
        raw = source_payloads[relative]
        row = _owner_entry(
            owner_app=SCHEDULER_BASELINE_APP,
            relative=relative,
            after=raw,
            after_sha=_sha(raw),
            diff_root=diff_root,
            source_kind="INDEPENDENTLY_REVIEWED_BATCH1_OR_BATCH3_SYNC_BYTES",
        )
        owner_records.append(row)
        if row["classification"] != "SAME_ALREADY_PRESENT":
            delta_records.append(row)

    candidate_id = "research-hourly-preselection-20261013-r8-candidate"
    candidate_root = root / "scheduler" / candidate_id
    candidate_app = candidate_root / "app"
    candidate_root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(SCHEDULER_BASELINE_APP, candidate_app, symlinks=True)
    if api_release.inventory_tree(candidate_app) != baseline_inventory:
        raise ValueError("scheduler candidate baseline copy inventory mismatch")
    for row in delta_records:
        relative = str(row["path"])
        source = source_payloads[relative]
        target = _relative_file(candidate_app, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.chmod(stat.S_IMODE(target.stat().st_mode) | stat.S_IWUSR)
            open_mode = "wb"
        else:
            open_mode = "xb"
        with target.open(open_mode) as handle:
            handle.write(source)
        shutil.copystat(REPO_ROOT / relative, target, follow_symlinks=False)
        expected = str(row["after_sha256"])
        if _file_sha(target) != expected:
            raise ValueError(f"scheduler candidate delta SHA mismatch: {relative}")
    candidate_inventory = api_release.inventory_tree(candidate_app)
    baseline_by_path = {str(row["path"]): row for row in baseline_inventory}
    candidate_by_path = {str(row["path"]): row for row in candidate_inventory}
    delta_paths = {str(row["path"]) for row in delta_records}
    removed = sorted(set(baseline_by_path) - set(candidate_by_path))
    added = sorted((set(candidate_by_path) - set(baseline_by_path)) - delta_paths)
    altered = sorted(
        path for path in set(baseline_by_path) & set(candidate_by_path)
        if path not in delta_paths and baseline_by_path[path] != candidate_by_path[path]
    )
    if removed or added or altered:
        raise ValueError(f"scheduler non-delta changes found: removed={removed} added={added} altered={altered}")
    delta_inventory = [candidate_by_path[path] for path in sorted(delta_paths)]
    preserved = [baseline_by_path[path] for path in sorted(baseline_by_path) if path not in delta_paths]
    preserved_candidate = [candidate_by_path[path] for path in sorted(baseline_by_path) if path not in delta_paths]
    if preserved != preserved_candidate:
        raise ValueError("scheduler non-delta owner bytes are not preserved")

    candidate_manifest_path = candidate_root / "release-manifest.json"
    module_contract_path = candidate_app / "deployment" / "api_module_contracts.json"
    module_contract_sha = _file_sha(module_contract_path) if module_contract_path.is_file() else None
    candidate_manifest = {
        "schema_version": "v4.release_candidate.v1",
        "candidate_status": "READY_FOR_REVIEW",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "owner": "com.lexi.v35.scheduler",
        "baseline": {
            "release_id": candidate["release_id"],
            "release_root": str(SCHEDULER_BASELINE_APP.parent),
            "app_root": str(SCHEDULER_BASELINE_APP),
            "manifest_path": str(manifest_path),
            "manifest_sha256": SCHEDULER_BASELINE_MANIFEST_SHA,
            "plist_backup_path": str(SCHEDULER_PLIST_BACKUP),
            "plist_backup_sha256": SCHEDULER_BACKUP_PLIST_SHA,
        },
        "candidate": {
            "release_id": candidate_id,
            "root": str(candidate_root),
            "app_root": str(candidate_app),
            "module_role": "gateway",
            "module_contract_sha256": module_contract_sha,
            "formal_release_root": str(Path(SCHEDULER_BASELINE_APP.parent).parent),
            "data_copy_performed": False,
            "runtime_venv_copied": False,
            "ignored_runtime_data_copied": False,
        },
        "reviewed_owner_deltas": delta_records,
        "source_diffs": owner_records,
        "application_inventory": {
            "entry_count": len(candidate_inventory),
            "aggregate_sha256": api_release.inventory_digest(candidate_inventory),
            "entries": candidate_inventory,
        },
        "non_delta_owner_bytes_preserved": True,
        "non_delta_path_count": len(preserved),
        "non_delta_inventory_sha256": api_release.inventory_digest(preserved),
        "changed_path_inventory_sha256": api_release.inventory_digest(delta_inventory),
        "scheduler_workload_bytes_preserved": baseline_by_path.get("contracts/runtime_workloads.json") == candidate_by_path.get("contracts/runtime_workloads.json"),
        "data_copy_performed": False,
    }
    _write_scheduler_manifest(candidate_manifest_path, candidate_manifest)
    identity = builder._stage_scheduler_identity(
        source_plist=SCHEDULER_PLIST_BACKUP,
        candidate_root=candidate_root,
        release_id=candidate_id,
        manifest_path=candidate_manifest_path,
        manifest_sha256=_file_sha(candidate_manifest_path),
    )
    original_plist = plistlib.loads(SCHEDULER_PLIST_BACKUP.read_bytes())
    candidate_plist = plistlib.loads(Path(identity["path"]).read_bytes())
    schedule_fields = (
        "StartCalendarInterval", "StartInterval", "RunAtLoad", "KeepAlive",
        "WatchPaths", "QueueDirectories", "StartOnMount",
    )
    if any(original_plist.get(key) != candidate_plist.get(key) for key in schedule_fields):
        raise ValueError("scheduler staged schedule fields differ from owner")
    preserved_roots = (
        "V35_DATA_ROOT", "V35_PRESELECTION_INPUT_ROOT", "V35_SHARED_DATA_ROOT",
        "V35_STAGE_CENTER_SELECTION_ROOT", "V35_REVIEW_CORE_CLOSE_ROOT",
    )
    old_env = original_plist["EnvironmentVariables"]
    new_env = candidate_plist["EnvironmentVariables"]
    if any(old_env.get(key) != new_env.get(key) for key in preserved_roots):
        raise ValueError("scheduler staged owner roots changed")
    report = {
        "schema_version": "r8.scheduler_owner_candidate_preparation.v1",
        "candidate_status": "READY_FOR_REVIEW",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "candidate_manifest": str(candidate_manifest_path),
        "candidate_manifest_sha256": _file_sha(candidate_manifest_path),
        "staged_plist": identity,
        "schedule_fields_preserved": {key: candidate_plist.get(key) for key in schedule_fields},
        "calendar_slots_preserved": original_plist.get("StartCalendarInterval") == candidate_plist.get("StartCalendarInterval"),
        "run_at_load_preserved": original_plist.get("RunAtLoad") == candidate_plist.get("RunAtLoad"),
        "roots_preserved": {key: new_env[key] for key in preserved_roots},
        "source_diffs": owner_records,
        "non_delta_owner_bytes_preserved": True,
    }
    report_path = root / "scheduler" / "scheduler-owner-candidate-report-r8.json"
    _write_json(report_path, report)
    return {"report": report, "report_path": str(report_path)}


def _reuse_scheduler_candidate(root: Path) -> dict[str, Any]:
    """Reuse the already prepared v14 scheduler when every pinned identity is unchanged."""
    sys.path.insert(0, str(REPO_ROOT))
    from ops import api_release_integration as api_release

    if _file_sha(SCHEDULER_PLIST_BACKUP) != SCHEDULER_BACKUP_PLIST_SHA:
        raise ValueError("scheduler immutable R4 owner plist backup hash mismatch")
    owner_manifest = SCHEDULER_BASELINE_APP.parent / "release-manifest.json"
    if _file_sha(owner_manifest) != SCHEDULER_BASELINE_MANIFEST_SHA:
        raise ValueError("scheduler R4 owner manifest changed; v14 reuse is no longer valid")
    report_path = SCHEDULER_REUSE_REPORT
    report = _read_json(report_path)
    if (report.get("candidate_status") != "READY_FOR_REVIEW"
            or report.get("activation_status") != "NOT_ACTIVATED"
            or report.get("deployment_status") != "CANNOT_CONFIRM"
            or report.get("candidate_manifest_sha256") != SCHEDULER_REUSE_MANIFEST_SHA256
            or report.get("non_delta_owner_bytes_preserved") is not True
            or report.get("calendar_slots_preserved") is not True
            or report.get("run_at_load_preserved") is not True):
        raise ValueError("existing v14 scheduler candidate is not reusable under the frozen identity")
    manifest_path = Path(str(report.get("candidate_manifest") or ""))
    if _file_sha(manifest_path) != SCHEDULER_REUSE_MANIFEST_SHA256:
        raise ValueError("existing v14 scheduler candidate manifest SHA changed")
    candidate_manifest = _read_json(manifest_path)
    candidate_root = Path(str(candidate_manifest.get("candidate", {}).get("root") or ""))
    candidate_app = Path(str(candidate_manifest.get("candidate", {}).get("app_root") or ""))
    if (candidate_root.is_symlink() or candidate_app.is_symlink()
            or candidate_root != manifest_path.parent
            or api_release.inventory_tree(candidate_app) != candidate_manifest["application_inventory"]["entries"]
            or api_release.inventory_digest(api_release.inventory_tree(candidate_app))
            != candidate_manifest["application_inventory"]["aggregate_sha256"]):
        raise ValueError("existing v14 scheduler candidate inventory or root changed")
    for row in report.get("source_diffs", []):
        path = REPO_ROOT / str(row["path"])
        if _file_sha(path) != row.get("after_sha256"):
            raise ValueError(f"scheduler v14 source identity drifted; rebuild is not authorized here: {row['path']}")
    staged = report.get("staged_plist")
    if not isinstance(staged, dict):
        raise ValueError("existing v14 scheduler staged plist receipt is invalid")
    staged_path = Path(str(staged.get("path") or ""))
    if _file_sha(staged_path) != staged.get("sha256"):
        raise ValueError("existing v14 scheduler staged plist changed")
    source_plist = plistlib.loads(SCHEDULER_PLIST_BACKUP.read_bytes())
    candidate_plist = plistlib.loads(staged_path.read_bytes())
    schedule_fields = (
        "StartCalendarInterval", "StartInterval", "RunAtLoad", "KeepAlive",
        "WatchPaths", "QueueDirectories", "StartOnMount",
    )
    if any(source_plist.get(key) != candidate_plist.get(key) for key in schedule_fields):
        raise ValueError("reused scheduler calendar or RunAtLoad fields differ from the pinned owner")
    source_env = source_plist.get("EnvironmentVariables") or {}
    candidate_env = candidate_plist.get("EnvironmentVariables") or {}
    root_fields = (
        "V35_DATA_ROOT", "V35_PRESELECTION_INPUT_ROOT", "V35_SHARED_DATA_ROOT",
        "V35_STAGE_CENTER_SELECTION_ROOT", "V35_REVIEW_CORE_CLOSE_ROOT",
    )
    if any(source_env.get(key) != candidate_env.get(key) for key in root_fields):
        raise ValueError("reused scheduler external data roots differ from the pinned owner")

    reuse = {
        "schema_version": "r8.scheduler_owner_candidate_reuse.v1",
        "classification": "REUSED_EXISTING_V14_CANDIDATE_NO_REBUILD",
        "candidate_status": report["candidate_status"],
        "activation_status": report["activation_status"],
        "deployment_status": report["deployment_status"],
        "source_report_path": str(report_path),
        "source_report_sha256": _file_sha(report_path),
        "candidate_manifest_path": str(manifest_path),
        "candidate_manifest_sha256": _file_sha(manifest_path),
        "active_owner_manifest_sha256": _file_sha(owner_manifest),
        "active_owner_plist_sha256": _file_sha(SCHEDULER_PLIST_BACKUP),
        "source_delta_identities_unchanged": True,
        "candidate_inventory_exact": True,
        "schedule_fields_preserved": {key: candidate_plist.get(key) for key in schedule_fields},
        "external_roots_preserved": {key: candidate_env.get(key) for key in root_fields},
        "candidate_root": str(candidate_root),
        "candidate_app_root": str(candidate_app),
        "staged_plist": staged,
        "no_rebuild_performed": True,
    }
    reuse_path = root / "scheduler" / "reused-owner-candidate-reference-r8.json"
    _write_json(reuse_path, reuse)
    return {"report": report, "report_path": str(report_path), "reuse_receipt": reuse, "reuse_receipt_path": str(reuse_path)}


def _prepare_stage(root: Path) -> dict[str, Any]:
    sys.path.insert(0, str(REPO_ROOT))
    from ops import api_release_integration as api_release
    from ops import build_release_candidate as core
    from ops import build_release_candidate_stage as stage_builder
    from ops.stage_service_overlay_contract import (
        STAGE_SERVICE_BASE_PRESERVED_SOURCE_PATHS,
        STAGE_SERVICE_RELEASE_CLOSURE_PATHS,
        STAGE_SERVICE_RELEASE_CLOSURE_SHA256,
        STAGE_SERVICE_OVERLAY_PATHS,
    )

    if _file_sha(STAGE_PLIST_BACKUP) != STAGE_BACKUP_PLIST_SHA:
        raise ValueError("Stage R4 immutable primary plist backup hash mismatch")
    if _file_sha(DEADLINE_PLIST_BACKUP) != DEADLINE_BACKUP_PLIST_SHA:
        raise ValueError("HK deadline immutable plist backup hash mismatch")
    runtime = _read_json(RUNTIME_IDENTITY)
    service = runtime["services"]["com.lexi.stage-center.scheduler"]
    if service["plist_sha256"] != STAGE_BACKUP_PLIST_SHA:
        raise ValueError("Stage owner plist receipt SHA mismatch")
    stage_release_id = "futu-primary-afternoon-20261013-r8-candidate"
    candidate_root = root / "stage" / stage_release_id
    receipt_path = root / "stage" / "stage-build-receipt-r8.json"
    (root / "stage").mkdir(exist_ok=True)
    adoption_rule_path = BASE / "BATCH6B_CONCURRENT_SOURCE_ADOPTION_R8.json"
    adoption_rule = _read_json(adoption_rule_path)
    adoption_relative = str(adoption_rule["path"])
    adoption_snapshot = Path(str(adoption_rule["snapshot"]))
    adoption_sha = str(adoption_rule["observed_sha256"])
    if (adoption_rule.get("actor") != "UNKNOWN_CONCURRENT_OWNER"
            or adoption_rule.get("before_sha256") != "82a2ad10a6c2c83ca49ca325790eac037a56bbce5f02e6c45dbe0d516bf843a9"
            or adoption_sha != STAGE_SERVICE_RELEASE_CLOSURE_SHA256.get(adoption_relative)
            or _file_sha(adoption_snapshot) != adoption_sha
            or adoption_relative not in STAGE_SERVICE_OVERLAY_PATHS):
        raise ValueError("frozen concurrent Stage source adoption rule is invalid")
    source_overrides = {adoption_relative: adoption_snapshot}
    built = stage_builder.build_stage_service_candidate(
        source_root=REPO_ROOT,
        candidate_root=candidate_root,
        stage_plist_path=STAGE_PLIST_BACKUP,
        release_id=stage_release_id,
        receipt_path=receipt_path,
        overlay_paths=STAGE_SERVICE_OVERLAY_PATHS,
        source_overrides=source_overrides,
        generate_owner_consumer_source_evidence_compat=True,
    )
    candidate_app = candidate_root / "app"
    stage_manifest = _read_json(candidate_root / "release-manifest.json")
    deadline_identity = stage_builder._render_stage_service_binding(
        source_plist=DEADLINE_PLIST_BACKUP,
        candidate_root=candidate_root,
        release_id=stage_release_id,
        manifest_path=candidate_root / "release-manifest.json",
        manifest_sha256=_file_sha(candidate_root / "release-manifest.json"),
        runtime_python=Path(str(built["service_binding"]["runtime_python"])),
        source_runtime_python=Path(str(built["service_binding"]["source_runtime_python"])),
        service_label="com.lexi.stage-center.hk-deadline",
        deadline_only=True,
    )
    if _file_sha(candidate_app / "stage_center_tick_config.json") != built["service_binding"]["config_sha256"]:
        raise ValueError("deadline plist preparation changed the Stage candidate config")
    source_deadline = plistlib.loads(DEADLINE_PLIST_BACKUP.read_bytes())
    staged_deadline = plistlib.loads(Path(deadline_identity["path"]).read_bytes())
    if (source_deadline.get("StartCalendarInterval") != staged_deadline.get("StartCalendarInterval")
            or source_deadline.get("RunAtLoad") is not False
            or staged_deadline.get("RunAtLoad") is not False
            or staged_deadline["ProgramArguments"][-1] != "--deadline-only"):
        raise ValueError("candidate HK deadline binding changed its frozen eight-slot contract")
    if api_release.inventory_tree(candidate_app) != stage_manifest["application_inventory"]["entries"]:
        raise ValueError("Stage candidate app changed after its manifest and primary plist render")
    stage_overlay_paths = [
        str(row["path"]) for row in stage_manifest["source"]["stage_overlay"]["entries"]
    ]
    stage_diff_paths = list(stage_overlay_paths)
    if "stage_center_tick_config.json" not in stage_overlay_paths:
        stage_diff_paths.append("stage_center_tick_config.json")
    generated_consumer_path = "stage_center/consumer.py"
    generated_consumer_rows = list(built.get("candidate_generated_compat_sources", []))
    if (len(generated_consumer_rows) != 1
            or generated_consumer_rows[0].get("path") != generated_consumer_path
            or generated_consumer_rows[0].get("classification") != "GENERATED_COMPAT_SOURCE_CANDIDATE_ONLY"):
        raise ValueError("Stage candidate lacks the exact generated consumer compatibility receipt")
    generated_consumer = generated_consumer_rows[0]
    stage_diff_paths.append(generated_consumer_path)
    stage_diffs = _tree_diff_records(
        before_root=STAGE_BASELINE_APP,
        after_root=candidate_app,
        relatives=stage_diff_paths,
        diff_root=root / "owner-base-diffs" / "stage",
        source_kind="REVIEWED_STAGE_OVERLAY_OR_CANDIDATE_IDENTITY_RENDER",
    )
    node_preserve_rule_path = BASE / "BATCH6B_OWNER_PRESERVATION_NODE_ENTRY_R8.json"
    node_preserve_rule = _read_json(node_preserve_rule_path)
    cohort_preserve_rule_path = BASE / "BATCH6B_REMAINING_STAGE_OWNER_PRESERVATION_R8.json"
    cohort_preserve_rule = _read_json(cohort_preserve_rule_path)
    cohort_rules = {
        str(row["path"]): row for row in cohort_preserve_rule.get("paths", [])
        if isinstance(row, dict) and row.get("path")
    }
    node_path = str(node_preserve_rule.get("path") or "")
    expected_cohort_paths = set(STAGE_SERVICE_BASE_PRESERVED_SOURCE_PATHS) - {node_path}
    if (set(cohort_rules) != expected_cohort_paths
            or cohort_preserve_rule.get("owner_root") != str(STAGE_BASELINE_APP)
            or cohort_preserve_rule.get("owner_release") != "futu-primary-afternoon-20261012-r4"
            or cohort_preserve_rule.get("source_write_scope") !=
            "NONE for listed paths; only existing scoped packaging/contract tools may record owner-preserved hash category"):
        raise ValueError("Stage owner-preservation cohort rule does not match the pinned closure")
    generated_config_render = _verify_stage_config_identity_render(
        candidate_root=candidate_root,
        candidate_app=candidate_app,
        stage_manifest=stage_manifest,
        service_binding=built["service_binding"],
        stage_overlay_paths=stage_overlay_paths,
    )
    preserved_helpers = []
    for relative, expected_sha in sorted(STAGE_SERVICE_BASE_PRESERVED_SOURCE_PATHS.items()):
        if relative == node_path:
            rule_path = node_preserve_rule_path
            owner_snapshot = Path(str(node_preserve_rule.get("snapshot") or ""))
            rule_owner_sha = node_preserve_rule.get("owner_sha256")
            rule_owner_root = node_preserve_rule.get("owner_root")
            rule_current_sha = node_preserve_rule.get("canonical_sha256")
            rule_mode = "OWNER_BASE_PRESERVED"
            node_rule_matches = (
                node_preserve_rule.get("candidate_source") == "actual pinned Stage R4 owner exact bytes"
                and node_preserve_rule.get("canonical_write_scope") == "NONE"
            )
        else:
            rule_path = cohort_preserve_rule_path
            row = cohort_rules[relative]
            owner_snapshot = Path(str(row.get("snapshot") or ""))
            rule_owner_sha = row.get("owner_sha256")
            rule_owner_root = cohort_preserve_rule.get("owner_root")
            rule_current_sha = row.get("current_sha256_not_approved")
            rule_mode = row.get("mode")
            node_rule_matches = True
        canonical_path = REPO_ROOT / relative
        owner_sha = _file_sha(STAGE_BASELINE_APP / relative)
        snapshot_sha = _file_sha(owner_snapshot)
        candidate_sha = _file_sha(candidate_app / relative)
        canonical_sha = _file_sha(canonical_path)
        generated_config = relative == "stage_center_tick_config.json"
        generated_consumer_path_match = relative == generated_consumer_path
        candidate_sha_valid = (
            candidate_sha == generated_config_render["candidate_after_sha256"]
            if generated_config else (
                candidate_sha == generated_consumer.get("candidate_after_sha256")
                if generated_consumer_path_match else candidate_sha == expected_sha
            )
        )
        if (not node_rule_matches
                or rule_owner_root != str(STAGE_BASELINE_APP)
                or rule_owner_sha != expected_sha
                or rule_current_sha != canonical_sha
                or rule_mode != "OWNER_BASE_PRESERVED"
                or owner_sha != expected_sha or snapshot_sha != expected_sha or not candidate_sha_valid
                or relative in stage_overlay_paths):
            raise ValueError(f"Stage base-owned helper preservation proof failed: {relative}")
        preserved_helpers.append({
            "path": relative,
            "classification": (
                "GENERATED_IDENTITY_RENDER_FROM_EXACT_OWNER_SOURCE_NO_OVERLAY"
                if generated_config else (
                    "GENERATED_COMPAT_SOURCE_CANDIDATE_ONLY"
                    if generated_consumer_path_match else "OWNER_BASE_BYTES_PRESERVED_UNREVIEWED_CANONICAL_VARIANT_NOT_OVERLAID"
                )
            ),
            "owner_base_sha256": owner_sha,
            "frozen_owner_snapshot_sha256": snapshot_sha,
            "candidate_sha256": candidate_sha,
            "unreviewed_canonical_sha256": canonical_sha,
            "closure_required": relative in STAGE_SERVICE_RELEASE_CLOSURE_PATHS,
            "overlay_applied": False,
            "candidate_generated_compatibility_applied": generated_consumer_path_match,
            "preservation_rule_path": str(rule_path),
            "preservation_rule_sha256": _file_sha(rule_path),
            "identity_render_receipt_path": (
                generated_config_render["receipt_path"] if generated_config else None
            ),
        })
    adoption_candidate_sha = _file_sha(candidate_app / adoption_relative)
    if adoption_candidate_sha != adoption_sha:
        raise ValueError("Stage candidate concurrent adoption bytes differ from the exact frozen snapshot")
    concurrent_source_adoption = {
        "path": adoption_relative,
        "attribution": "UNKNOWN_CONCURRENT_OWNER",
        "snapshot": str(adoption_snapshot),
        "snapshot_sha256": _file_sha(adoption_snapshot),
        "canonical_workspace_sha256_read_only": _file_sha(REPO_ROOT / adoption_relative),
        "candidate_sha256": adoption_candidate_sha,
        "source_kind": "PINNED_SOURCE_OVERRIDE",
        "adoption_rule_sha256": _file_sha(adoption_rule_path),
    }
    for row in stage_diffs:
        if row.get("path") == adoption_relative:
            row["source_kind"] = "UNKNOWN_CONCURRENT_OWNER_EXACT_FROZEN_ADOPTION"
            row["source_snapshot_sha256"] = adoption_sha
        elif row.get("path") == generated_consumer_path:
            row["source_kind"] = "GENERATED_COMPAT_SOURCE_CANDIDATE_ONLY"
            if (row.get("before_sha256") != generated_consumer.get("owner_before_sha256")
                    or row.get("after_sha256") != generated_consumer.get("candidate_after_sha256")
                    or not isinstance(row.get("unified_diff_sha256"), str)
                    or len(row["unified_diff_sha256"]) != 64
                    or not isinstance(generated_consumer.get("unified_diff_sha256"), str)
                    or len(generated_consumer["unified_diff_sha256"]) != 64
                    or row.get("unified_diff_hunk_count") != 1):
                raise ValueError("Stage generated consumer full diff differs from its exact one-field receipt")
    frozen_closure = _read_json(MODULE_CLOSURE)["candidate_dependency_additions"]
    candidate_modules = []
    for row in frozen_closure:
        relative = str(row["path"])
        frozen_sha = str(row["source_sha256"])
        candidate_sha = _file_sha(candidate_app / relative)
        if candidate_sha != frozen_sha:
            raise ValueError(f"Stage candidate frozen dependency addition SHA mismatch: {relative}")
        candidate_modules.append({
            "path": relative,
            "snapshot": row["snapshot"],
            "frozen_sha256": frozen_sha,
            "canonical_sha256": _file_sha(REPO_ROOT / relative),
            "candidate_sha256": candidate_sha,
            "write_scope": "CANDIDATE_ADDITION_ONLY_CANONICAL_READ_ONLY",
        })
    report = {
        "schema_version": "r8.stage_owner_candidate_preparation.v1",
        "candidate_status": built["candidate_status"],
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "candidate_root": str(candidate_root),
        "candidate_manifest_sha256": built["manifest_sha256"],
        "primary_service_binding": built["service_binding"],
        "deadline_only_service_binding": deadline_identity,
        "deadline_calendar_preserved": source_deadline["StartCalendarInterval"] == staged_deadline["StartCalendarInterval"],
        "deadline_run_at_load_false": staged_deadline.get("RunAtLoad") is False,
        "deadline_only_flag_preserved": staged_deadline["ProgramArguments"][-1] == "--deadline-only",
        "stage_overlay_paths": list(built["stage_overlay_paths"]),
        "owner_base_diffs": stage_diffs,
        "generated_stage_config_identity_render": generated_config_render,
        "generated_candidate_consumer_compatibility": {
            **generated_consumer,
            "full_owner_base_diff_path": next(
                row["diff_path"] for row in stage_diffs if row.get("path") == generated_consumer_path
            ),
        },
        "frozen_preselection_candidate_additions": candidate_modules,
        "base_preserved_required_closure_paths": preserved_helpers,
        "unknown_owner_concurrent_source_adoption": concurrent_source_adoption,
        "non_overlay_active_release_bytes_preserved": stage_manifest["source"]["stage_overlay"]["non_overlay_active_release_bytes_preserved"],
        "pinned_legacy_cache_preserved": stage_manifest["source"]["stage_overlay"]["pinned_legacy_cache_exclusions"],
        "legacy_inventory_digest_compatibility": stage_manifest["source"]["integration_base"]["inventory_digest_compatibility"],
        "config_external_data_roots_preserved": built["service_binding"]["source_config_roots_preserved"],
        "manifest_path": str(candidate_root / "release-manifest.json"),
        "receipt_path": str(receipt_path),
        "candidate_inventory_sha256": api_release.inventory_digest(stage_manifest["application_inventory"]["entries"]),
    }
    report_path = root / "stage" / "stage-owner-candidate-report-r8.json"
    _write_json(report_path, report)
    return {"report": report, "report_path": str(report_path)}


def prepare_api_only_rebase(
    output_root: Path = API_STAGE_CLIENT_REBASE_OUTPUT_ROOT,
) -> dict[str, Any]:
    """Build only the API client-repair candidate from the exact live v24 owner."""
    output_root = output_root.resolve()
    if not output_root.is_relative_to(BASE.resolve()):
        raise ValueError("candidate output must remain inside the frozen R8 receipt workspace")
    output_root.mkdir(parents=True, exist_ok=False)
    (output_root / "logs").mkdir()
    api = _prepare_api_stage_client_candidate(output_root)
    result = {
        "schema_version": "r8.api_stage_client_owner_candidate.v1",
        "candidate_status": "READY_FOR_INDEPENDENT_REVIEW",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "output_root": str(output_root),
        "api": api,
        "verification_gaps": [
            "candidate API was not activated or restarted",
            "API endpoint and browser page reload remain CANNOT_CONFIRM",
            "natural-slot acceptance remains CANNOT_CONFIRM",
            "current live owner must be compare-and-swapped against its exact then-current pointer before future activation",
        ],
        "forbidden_actions_performed": [],
    }
    _write_json(output_root / "OWNER_CANDIDATES_R8.json", result)
    return result


def prepare_candidates(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    output_root = output_root.resolve()
    if not output_root.is_relative_to(BASE.resolve()):
        raise ValueError("candidate output must remain inside the frozen R8 receipt workspace")
    output_root.mkdir(parents=True, exist_ok=False)
    (output_root / "logs").mkdir()
    source_bytes, categories = _api_source_bytes()
    api = _prepare_api(output_root, source_bytes, categories)
    scheduler = _reuse_scheduler_candidate(output_root)
    stage = _prepare_stage(output_root)
    result = {
        "schema_version": "r8.pool_stage_owner_candidates.v1",
        "candidate_status": "READY_FOR_INDEPENDENT_REVIEW",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "output_root": str(output_root),
        "api": api,
        "scheduler": scheduler,
        "stage": stage,
        "forbidden_actions_performed": [],
    }
    _write_json(output_root / "OWNER_CANDIDATES_R8.json", result)
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--api-only-rebase", action="store_true")
    parser.add_argument("--scheduler-only-rebase", action="store_true")
    args = parser.parse_args()
    if args.api_only_rebase and args.scheduler_only_rebase:
        parser.error("--api-only-rebase and --scheduler-only-rebase are mutually exclusive")
    if args.scheduler_only_rebase:
        result = _prepare_scheduler_owner_rebase(args.output_root or SCHEDULER_REBASE_OUTPUT_ROOT)
        print(json.dumps({
            "candidate_status": result["candidate_status"],
            "output_root": str(args.output_root or SCHEDULER_REBASE_OUTPUT_ROOT),
            "report_path": result["report_path"],
        }, ensure_ascii=False, indent=2))
    elif args.api_only_rebase:
        result = prepare_api_only_rebase(args.output_root or API_STAGE_CLIENT_REBASE_OUTPUT_ROOT)
        print(json.dumps({
            "candidate_status": result["candidate_status"],
            "output_root": result["output_root"],
            "reports": {"api": result["api"]["report_path"]},
        }, ensure_ascii=False, indent=2))
    else:
        result = prepare_candidates(args.output_root or OUTPUT_ROOT)
        print(json.dumps({
            "candidate_status": result["candidate_status"],
            "output_root": result["output_root"],
            "reports": {
                "api": result["api"]["report_path"],
                "scheduler": result["scheduler"]["report_path"],
                "stage": result["stage"]["report_path"],
            },
        }, ensure_ascii=False, indent=2))
