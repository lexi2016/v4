from __future__ import annotations

import hashlib
import json
from pathlib import Path
import plistlib

import pytest

from ops import api_release_integration as integration
from ops import build_release_candidate as release_builder


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _active_gateway(tmp_path: Path) -> dict[str, Path | str]:
    release_root = tmp_path / "active-gateway"
    app_root = release_root / "app"
    app_root.mkdir(parents=True)
    (app_root / "apps/api/v35_api").mkdir(parents=True)
    source_app = app_root / "apps/api/v35_api/app.py"
    source_app.write_text("LEGACY = True\n", encoding="utf-8")
    entries = integration.inventory_tree(app_root)
    manifest = {
        "schema_version": "v4.release_candidate.v1",
        "candidate": {"root": str(release_root), "app_root": str(app_root), "release_id": release_root.name},
        "application_inventory": {
            "entries": entries,
            "aggregate_sha256": integration.inventory_digest(entries),
        },
    }
    manifest_path = release_root / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    manifest_sha = _sha(manifest_path.read_bytes())
    plist_path = tmp_path / "LaunchAgents" / "com.lexi.v35.api-only.plist"
    plist_path.parent.mkdir()
    plist_path.write_bytes(plistlib.dumps({
        "Label": "com.lexi.v35.api-only",
        "ProgramArguments": [
            "/usr/bin/env", "RESEARCH_ONLY=1", "production_allowed=false",
            "buy_gate_updated=false", "orders_sent=false",
            "V35_DATA_ROOT=/research/data", "V35_STAGE_CENTER_SELECTION_ROOT=/stage/selection",
            f"V35_APP_ROOT={app_root}", f"V35_RELEASE_ID={release_root.name}",
            f"V35_RELEASE_MANIFEST_PATH={manifest_path}", f"V35_RELEASE_MANIFEST_SHA256={manifest_sha}",
            f"PYTHONPATH={app_root / 'upstreams'}:{app_root}",
            "/usr/bin/python3", "-m", "apps.api.v35_api.run",
            "--host", "127.0.0.1", "--port", "8873",
        ],
        "WorkingDirectory": str(app_root),
    }, fmt=plistlib.FMT_XML))
    return {"root": release_root, "app": app_root, "manifest": manifest_path, "plist": plist_path}


def _bootstrap_receipt(active: dict[str, Path | str], source_root: Path, *, target_role: str) -> Path:
    active_identity = integration.read_active_release(Path(str(active["plist"])), role="gateway")
    files = {
        "apps/api/v35_api/app.py": b"MODULE_ROLE = True\n",
        "apps/api/v35_api/module_proxy.py": b"PROXY = True\n",
        "apps/api/v35_api/run.py": b"ROLE = True\n",
        "deployment/api_module_contracts.json": Path("deployment/api_module_contracts.json").read_bytes(),
    }
    entries = []
    for relative, content in sorted(files.items()):
        target = source_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        base = Path(str(active["app"])) / relative
        before = base.read_bytes() if base.exists() else None
        if before is None:
            diff_sha = None
            hunk_count = None
        else:
            import difflib
            lines = list(difflib.unified_diff(
                before.decode().splitlines(), content.decode().splitlines(),
                fromfile="before", tofile="after", n=0, lineterm="",
            ))
            diff_sha = _sha(("\n".join(lines) + ("\n" if lines else "")).encode())
            hunk_count = sum(line.startswith("@@") for line in lines)
        entries.append({
            "path": relative,
            "before_sha256": _sha(before) if before is not None else None,
            "after_sha256": _sha(content),
            "unified_diff_sha256": diff_sha,
            "unified_diff_hunk_count": hunk_count,
        })
    receipt = {
        "schema_version": integration.DELTA_SCHEMA_VERSION,
        "base": integration._base_binding(active_identity),
        "target_role": target_role,
        "base_role": "gateway",
        "entries": entries,
    }
    path = source_root.parent / "api-integration-delta-receipt.json"
    path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def _module_candidate(tmp_path: Path, role: str) -> tuple[dict[str, Path | str], Path]:
    active = _active_gateway(tmp_path)
    source = tmp_path / "source"
    receipt = _bootstrap_receipt(active, source, target_role=role)
    candidate = tmp_path / f"{role}-candidate"
    candidate.mkdir()
    details = integration.build_integrated_app(
        active_api_plist_path=Path(str(active["plist"])), source_root=source,
        candidate_root=candidate, delta_receipt_path=receipt, role=role, base_role="gateway",
        explicit_untracked_paths=(
            "apps/api/v35_api/module_proxy.py", "apps/api/v35_api/run.py",
            "deployment/api_module_contracts.json",
        ),
    )
    entries = integration.inventory_tree(candidate / "app")
    manifest = {
        "schema_version": "v4.release_candidate.v1",
        "candidate": {
            "root": str(candidate), "app_root": str(candidate / "app"),
            "release_id": candidate.name, "module_role": role,
            "module_contract_sha256": _sha((candidate / "app/deployment/api_module_contracts.json").read_bytes()),
        },
        "application_inventory": {
            "entries": entries, "aggregate_sha256": integration.inventory_digest(entries),
        },
        "api_integration": details,
    }
    manifest_path = candidate / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return active, candidate


@pytest.mark.parametrize("role", ["stage", "manager"])
def test_module_candidate_has_role_bound_manifest_and_independent_lock(tmp_path: Path, role: str) -> None:
    active, candidate = _module_candidate(tmp_path, role)
    role_config = integration.module_role_contract()["roles"][role]
    launch_agents = tmp_path / "LaunchAgents"
    role_plist = launch_agents / role_config["plist_name"]
    verification = integration.verify_api_release_candidate(
        candidate_root=candidate,
        active_api_plist_path=Path(str(active["plist"])),
        role=role,
        base_role="gateway",
        lock_plist_path=role_plist,
    )
    assert verification["status"] == "PASS"
    assert verification["delta_paths"] == [
        "apps/api/v35_api/app.py",
        "apps/api/v35_api/module_proxy.py",
        "apps/api/v35_api/run.py",
        "deployment/api_module_contracts.json",
    ]
    assert Path(verification["shared_lock_path"]).name == role_config["lock_name"]
    role_manifest_path = candidate / "release-manifest.json"
    role_manifest = json.loads(role_manifest_path.read_text())
    role_manifest_sha = _sha(role_manifest_path.read_bytes())
    role_plist.write_bytes(plistlib.dumps({
        "Label": role_config["label"],
        "ProgramArguments": [
            "/usr/bin/env",
            f"V35_API_ROLE={role}",
            f"V35_API_PORT={role_config['port']}",
            f"V35_APP_ROOT={candidate / 'app'}",
            f"V35_RELEASE_ID={candidate.name}",
            f"V35_RELEASE_MANIFEST_PATH={role_manifest_path}",
            f"V35_RELEASE_MANIFEST_SHA256={role_manifest_sha}",
        ],
    }, fmt=plistlib.FMT_XML))
    readback = integration.read_active_release(role_plist, role=role)
    assert readback["module_role"] == role
    with integration.shared_api_release_lock(role_plist, role=role) as lease:
        activated = integration.verify_api_release_candidate(
            candidate_root=candidate,
            active_api_plist_path=role_plist,
            role=role,
            base_role="gateway",
            active_pointer="candidate",
            lock_lease=lease,
            require_shared_lock=True,
        )
    assert activated["status"] == "PASS"


def test_role_lock_paths_are_independent_and_wrong_plist_is_rejected(tmp_path: Path) -> None:
    names = {
        role: tmp_path / config["plist_name"]
        for role, config in integration.module_role_contract()["roles"].items()
    }
    paths = {role: integration.api_release_lock_path(path, role=role) for role, path in names.items()}
    assert len(set(paths.values())) == 3
    with pytest.raises(ValueError, match="API_RELEASE_LOCK_POINTER_PATH_INVALID"):
        integration.api_release_lock_path(names["manager"], role="stage")


@pytest.mark.parametrize("role", ["stage", "manager"])
def test_prepare_module_cutover_preserves_roots_and_pins_role(tmp_path: Path, role: str) -> None:
    active, candidate = _module_candidate(tmp_path, role)
    source_plist_before = Path(str(active["plist"])).read_bytes()
    manifest_path = candidate / "release-manifest.json"
    manifest_sha = _sha(manifest_path.read_bytes())
    from ops.prepare_api_only_cutover import extract_environment, render_module_cutover

    plan = render_module_cutover(
        source_active_plist_path=Path(str(active["plist"])),
        candidate_root=candidate,
        release_id=candidate.name,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha,
        role=role,
        source_root=tmp_path / "source",
    )
    staged_path = Path(str(plan["candidate_plist"]["path"]))
    staged_plist = plistlib.loads(staged_path.read_bytes())
    env = extract_environment(staged_plist)
    role_config = integration.module_role_contract()["roles"][role]
    assert staged_plist["Label"] == role_config["label"]
    assert env["V35_API_ROLE"] == role
    assert env["V35_API_PORT"] == str(role_config["port"])
    assert env["V35_DATA_ROOT"] == "/research/data"
    assert env["V35_STAGE_CENTER_SELECTION_ROOT"] == "/stage/selection"
    assert env["production_allowed"] == "false"
    assert env["buy_gate_updated"] == "false"
    assert env["orders_sent"] == "false"
    assert "--port" in staged_plist["ProgramArguments"]
    port_at = staged_plist["ProgramArguments"].index("--port")
    assert staged_plist["ProgramArguments"][port_at + 1] == str(role_config["port"])
    assert Path(str(active["plist"])).read_bytes() == source_plist_before
    assert plan["activation_status"] == "NOT_ACTIVATED"
    assert plan["port_check"]["status"] == "NOT_RUN"
    assert plan["release_lock"]["path"].endswith(role_config["lock_name"])


def test_module_delta_rejects_sibling_role_code() -> None:
    with pytest.raises(ValueError, match="API_RELEASE_MODULE_DELTA_PATH_REJECTED"):
        integration._assert_role_delta_paths(
            ["v4/manager_research/service.py"], role="stage", bootstrap=False,
        )


def test_module_builder_creates_full_app_candidate_manifest_plist_and_plan(tmp_path: Path) -> None:
    active = _active_gateway(tmp_path)
    source = tmp_path / "source"
    receipt = _bootstrap_receipt(active, source, target_role="stage")
    candidate = tmp_path / "stage-candidate"
    result = release_builder.build_module_candidate(
        source_root=source,
        candidate_root=candidate,
        active_api_plist_path=Path(str(active["plist"])),
        release_id=candidate.name,
        role="stage",
        api_integration_delta_receipt_path=receipt,
        formal_release_root=tmp_path / "formal-gateway-releases",
        include_untracked_paths=(
            "apps/api/v35_api/module_proxy.py", "apps/api/v35_api/run.py",
            "deployment/api_module_contracts.json",
        ),
    )
    assert result["candidate_status"] == "READY_FOR_REVIEW"
    assert result["activation_status"] == "NOT_ACTIVATED"
    assert result["active_plist_changed"] is False
    manifest = json.loads((candidate / "release-manifest.json").read_text())
    assert manifest["candidate"]["module_role"] == "stage"
    assert (candidate / "app/apps/api/v35_api/app.py").read_bytes() == (source / "apps/api/v35_api/app.py").read_bytes()
    staged = Path(result["staged_plist"]["path"])
    assert staged.is_file()
    assert Path(result["cutover_plan"]).is_file()
