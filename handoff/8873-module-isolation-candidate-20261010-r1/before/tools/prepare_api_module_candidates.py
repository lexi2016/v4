#!/usr/bin/env python3
"""Prepare three role-isolated API release candidates from the live source root.

This tool is preparation-only. It reads the current 8873 plist and complete
active app snapshot, creates a four-file bootstrap delta, then calls the
existing API candidate builder for gateway, Stage, and Manager. It never
changes a LaunchAgent, starts a process, or calls launchctl.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import plistlib
import stat
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.v35_api.module_proxy import load_module_contract
from ops import api_release_integration as integration
from ops import build_release_candidate as release_builder


LIVE_ROOT = Path(
    "/REDACTED_LOCAL_HOME/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/"
    "candidate/issue32_preselection_api_actual_r4"
)
LIVE_APP = LIVE_ROOT / "app"
ACTIVE_GATEWAY_PLIST = Path("/REDACTED_LOCAL_HOME/Library/LaunchAgents/com.lexi.v35.api-only.plist")
PACKAGE_ROOT = Path(
    "/REDACTED_LOCAL_HOME/Desktop/学习/agents调试/V4_MODULE_API_IMPLEMENTATION_20261009"
)
RUN_ROOT = PACKAGE_ROOT / "candidate" / "module_api_isolation_r5c_20261009"
SOURCE_ROOT = RUN_ROOT / "source"
EVIDENCE_ROOT = RUN_ROOT / "evidence"
ROLE_FILES = (
    "apps/api/v35_api/app.py",
    "apps/api/v35_api/run.py",
    "apps/api/v35_api/module_proxy.py",
    "deployment/api_module_contracts.json",
)
NEW_FILES = (
    "apps/api/v35_api/module_proxy.py",
    "deployment/api_module_contracts.json",
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _replace_once(text: str, before: str, after: str, label: str) -> str:
    count = text.count(before)
    if count != 1:
        raise ValueError(f"{label}_ANCHOR_COUNT:{count}")
    return text.replace(before, after, 1)


def _patch_live_app(source: str) -> str:
    source = _replace_once(
        source,
        "from fastapi.staticfiles import StaticFiles\n",
        "from fastapi.staticfiles import StaticFiles\n"
        "from apps.api.v35_api.module_proxy import configure_module_role\n",
        "APP_ROLE_IMPORT",
    )
    source = _replace_once(
        source,
        "    preselection_source_root: Path | str | None = None,\n"
        ") -> FastAPI:\n"
        "    app = FastAPI(title=\"V3.5\", version=\"0.1.0\")\n",
        "    preselection_source_root: Path | str | None = None,\n"
        "    module_role: str = \"combined\",\n"
        ") -> FastAPI:\n"
        "    if module_role not in {\"combined\", \"gateway\", \"stage\", \"manager\"}:\n"
        "        raise ValueError(\"V35_API_ROLE_UNSUPPORTED\")\n"
        "    if module_role != \"combined\" and stage_center_selection_root is None and not os.environ.get(\"V35_STAGE_CENTER_SELECTION_ROOT\"):\n"
        "        raise ValueError(\"V35_API_ROLE_REQUIRES_SHARED_STAGE_SELECTION_ROOT\")\n"
        "    app = FastAPI(\n"
        "        title=\"V3.5\", version=\"0.1.0\",\n"
        "        docs_url=None if module_role in {\"stage\", \"manager\"} else \"/docs\",\n"
        "        redoc_url=None if module_role in {\"stage\", \"manager\"} else \"/redoc\",\n"
        "        openapi_url=None if module_role in {\"stage\", \"manager\"} else \"/openapi.json\",\n"
        "    )\n",
        "APP_ROLE_FACTORY",
    )
    return _replace_once(source, "\n    return app\n", "\n    return configure_module_role(app, module_role)\n", "APP_ROLE_FILTER")


def _patch_live_run(source: str) -> str:
    source = _replace_once(
        source,
        "from apps.api.v35_api.app import create_app\n",
        "from apps.api.v35_api.app import create_app\n"
        "from apps.api.v35_api.module_proxy import load_module_contract\n",
        "RUN_ROLE_IMPORT",
    )
    source = _replace_once(
        source,
        "    parser.add_argument(\"--port\", default=8873, type=int)\n",
        "    parser.add_argument(\"--port\", type=int)\n"
        "    parser.add_argument(\"--role\", choices=(\"gateway\", \"stage\", \"manager\", \"combined\"))\n",
        "RUN_ROLE_ARGS",
    )
    source = _replace_once(
        source,
        "    arguments = parser.parse_args()\n"
        "    stage_root = arguments.stage_selection_root or (\n",
        "    arguments = parser.parse_args()\n"
        "    environment_role = os.environ.get(\"V35_API_ROLE\")\n"
        "    if arguments.role is not None and environment_role is not None and arguments.role != environment_role:\n"
        "        parser.error(\"--role conflicts with V35_API_ROLE\")\n"
        "    role = arguments.role or environment_role or \"gateway\"\n"
        "    if role not in {\"gateway\", \"stage\", \"manager\", \"combined\"}:\n"
        "        parser.error(\"V35_API_ROLE is unsupported\")\n"
        "    if role == \"combined\":\n"
        "        role_target = {\"host\": \"127.0.0.1\", \"port\": 8873}\n"
        "    else:\n"
        "        role_target = load_module_contract()[\"roles\"][role]\n"
        "    if arguments.host != role_target[\"host\"]:\n"
        "        parser.error(\"the selected API role only binds to its contracted loopback host\")\n"
        "    if arguments.port is not None and arguments.port != role_target[\"port\"]:\n"
        "        parser.error(\"the selected API role only binds to its contracted port\")\n"
        "    environment_port = os.environ.get(\"V35_API_PORT\")\n"
        "    if environment_port is not None and environment_port != str(role_target[\"port\"]):\n"
        "        parser.error(\"V35_API_PORT conflicts with the selected API role\")\n"
        "    port = role_target[\"port\"]\n"
        "    stage_root = arguments.stage_selection_root or (\n",
        "RUN_ROLE_RESOLVE",
    )
    source = _replace_once(
        source,
        "    if arguments.stage_mode not in {\"shared\", \"local\"}:\n",
        "    if role != \"combined\" and arguments.stage_mode != \"shared\":\n"
        "        parser.error(\"isolated API roles require shared Stage selection mode\")\n"
        "    if arguments.stage_mode not in {\"shared\", \"local\"}:\n",
        "RUN_SHARED_STAGE_MODE",
    )
    source = _replace_once(
        source,
        "    config = ServerConfig(host=arguments.host, port=arguments.port)\n",
        "    config = ServerConfig(host=arguments.host, port=port)\n",
        "RUN_ROLE_PORT",
    )
    source = _replace_once(
        source,
        "            stage_center_selection_root=stage_root,\n",
        "            stage_center_selection_root=stage_root,\n"
        "            module_role=role,\n",
        "RUN_ROLE_FACTORY",
    )
    return source


def _write_delta_receipt(role: str) -> Path:
    active = integration.read_active_release(ACTIVE_GATEWAY_PLIST, role="gateway")
    entries: list[dict[str, Any]] = []
    for relative in sorted(ROLE_FILES):
        target = SOURCE_ROOT / relative
        raw = target.read_bytes()
        base = Path(str(active["app_root"])) / relative
        before = base.read_bytes() if base.is_file() else None
        if before is None:
            diff_sha = None
            hunk_count = None
        else:
            diff_sha, hunk_count = integration._diff_proof(before, raw)
        entries.append({
            "path": relative,
            "before_sha256": _sha(before) if before is not None else None,
            "after_sha256": _sha(raw),
            "unified_diff_sha256": diff_sha,
            "unified_diff_hunk_count": hunk_count,
        })
    receipt = {
        "schema_version": integration.DELTA_SCHEMA_VERSION,
        "base": integration._base_binding(active),
        "target_role": role,
        "base_role": "gateway",
        "entries": entries,
    }
    path = RUN_ROOT / f"{role}-api-integration-delta-receipt.json"
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return path


def prepare() -> dict[str, Any]:
    if RUN_ROOT.exists():
        raise FileExistsError(f"refusing to overwrite module candidate run: {RUN_ROOT}")
    if not LIVE_APP.is_dir() or not ACTIVE_GATEWAY_PLIST.is_file():
        raise FileNotFoundError("current API root or gateway LaunchAgent is missing")
    contract = load_module_contract()
    gateway_sha = _sha((LIVE_APP / "apps/api/v35_api/app.py").read_bytes())
    gateway_source_sha = contract["contract_source"]["sha256"]
    if gateway_sha != "5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5":
        raise ValueError("LIVE_API_APP_SHA_CHANGED")
    with ACTIVE_GATEWAY_PLIST.open("rb") as handle:
        plist = plistlib.load(handle)
    env = integration._plist_environment(plist)
    if plist.get("Label") != "com.lexi.v35.api-only" or env.get("V35_APP_ROOT") != str(LIVE_APP):
        raise ValueError("ACTIVE_GATEWAY_BINDING_CHANGED")
    RUN_ROOT.mkdir(parents=True)
    SOURCE_ROOT.mkdir()
    EVIDENCE_ROOT.mkdir()
    app_source = _patch_live_app((LIVE_APP / "apps/api/v35_api/app.py").read_text(encoding="utf-8"))
    run_source = _patch_live_run((LIVE_APP / "apps/api/v35_api/run.py").read_text(encoding="utf-8"))
    for relative, raw in (
        (ROLE_FILES[0], app_source.encode("utf-8")),
        (ROLE_FILES[1], run_source.encode("utf-8")),
        (ROLE_FILES[2], (REPO_ROOT / ROLE_FILES[2]).read_bytes()),
        (ROLE_FILES[3], (REPO_ROOT / ROLE_FILES[3]).read_bytes()),
    ):
        target = SOURCE_ROOT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        active_source = LIVE_APP / relative
        if active_source.is_file():
            target.chmod(stat.S_IMODE(active_source.stat().st_mode))

    roles = ("gateway", "stage", "manager")
    output: dict[str, Any] = {
        "schema_version": "v4.api_module_candidate_bundle.v1",
        "status": "READY_FOR_INDEPENDENT_REVIEW",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "source": {
            "app_root": str(LIVE_APP),
            "app_manifest_sha256": _sha((LIVE_ROOT / "release-manifest.json").read_bytes()),
            "app_py_before_sha256": gateway_sha,
            "plist_path": str(ACTIVE_GATEWAY_PLIST),
            "plist_sha256": _sha(ACTIVE_GATEWAY_PLIST.read_bytes()),
            "route_contract_source_schema": gateway_source_sha,
            "complete_active_app_copied_by_existing_builder": True,
            "working_tree_overlaid": False,
        },
        "candidates": {},
    }
    for role in roles:
        receipt_path = _write_delta_receipt(role)
        candidate_id = f"{role}-api-module-split-r5c-20261009"
        candidate_root = RUN_ROOT / "releases" / candidate_id
        candidate_root.parent.mkdir(parents=True, exist_ok=True)
        receipt = release_builder.build_module_candidate(
            source_root=SOURCE_ROOT,
            candidate_root=candidate_root,
            active_api_plist_path=ACTIVE_GATEWAY_PLIST,
            release_id=candidate_id,
            role=role,
            api_integration_delta_receipt_path=receipt_path,
            base_role="gateway",
            bootstrap_transition=(role == "gateway"),
            formal_release_root=Path(contract["roles"]["gateway"]["release_root"]),
            receipt_path=EVIDENCE_ROOT / f"{role}-build-receipt.json",
            include_untracked_paths=NEW_FILES,
        )
        output["candidates"][role] = receipt
    bundle_path = EVIDENCE_ROOT / "BUILD_READBACK.json"
    bundle_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    output["bundle_path"] = str(bundle_path)
    return output


if __name__ == "__main__":
    print(json.dumps(prepare(), ensure_ascii=False, indent=2, sort_keys=True))
