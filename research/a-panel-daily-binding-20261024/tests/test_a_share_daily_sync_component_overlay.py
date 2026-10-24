from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ops import a_share_daily_sync_component_overlay as overlay


SHANGHAI = ZoneInfo("Asia/Shanghai")
OLD_APP_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
    "20260915-us-owner-handoff-disabled/app"
)


def _read(path: Path) -> bytes:
    return path.read_bytes()


def _prepare_fixture(tmp_path: Path) -> dict[str, Path | dict[str, object]]:
    release = tmp_path / "release"
    release.mkdir()
    fixed = release / "app" / "ops" / "a_share_daily_sync.py"
    fixed.parent.mkdir(parents=True)
    fixed.write_bytes(_read(overlay.FIXED_ENTRYPOINT))
    base_manifest = release / "release-manifest.json"
    base_manifest.write_bytes(_read(overlay.BASE_RELEASE_MANIFEST))
    component = release / "a-share-daily-sync-component-20261024-r1"
    evidence = tmp_path / "evidence"
    result = overlay.prepare_component(
        component,
        fixed_entry_path=fixed,
        base_release_manifest_path=base_manifest,
        evidence_root=evidence,
        now=datetime(2026, 10, 24, 15, 0, tzinfo=SHANGHAI),
    )
    return {
        "release": release,
        "fixed": fixed,
        "base_manifest": base_manifest,
        "component": component,
        "evidence": evidence,
        "result": result,
    }


def _install_test_shim(candidate: dict[str, Path | dict[str, object]]) -> bytes:
    fixed = candidate["fixed"]
    evidence = candidate["evidence"]
    assert isinstance(fixed, Path) and isinstance(evidence, Path)
    shim = (evidence / "entrypoint-shim.py").read_bytes()
    fixed.write_bytes(shim)
    return shim


def _run_loader_process(fixed: Path, component: Path, *, expect_failure: bool = False) -> subprocess.CompletedProcess[str]:
    script = r"""
import importlib
import inspect
import os
import sys
from pathlib import Path

app = Path(os.environ["PANEL_OLD_APP_ROOT"])
fixed = Path(os.environ["PANEL_FIXED_ENTRY"])
component = Path(os.environ["PANEL_COMPONENT_ROOT"])
sys.path.insert(0, str(app))
authority = importlib.import_module("ops.macos_research_panel_daily_authority")
name = "a_share_daily_sync_overlay_test"
try:
    module = authority._load_authority_module(fixed, name)
except Exception as error:
    assert os.environ.get("PANEL_EXPECT_FAILURE") == "1", repr(error)
    assert name not in sys.modules
    print(type(error).__name__ + ": " + str(error))
    raise SystemExit(0)
assert os.environ.get("PANEL_EXPECT_FAILURE") != "1"
assert sys.modules[name] is module
assert module.__file__ == str(component / "ops" / "a_share_daily_sync.py")
assert os.environ["V35_A_SYNC_TDX_PROTOCOL"] == "mac"
assert sys.path[0] == str(component)
parts = importlib.import_module("ops._a_share_daily_sync_parts")
assert Path(parts.__file__).resolve().is_relative_to(component.resolve())
assert callable(module.run)
assert list(inspect.signature(module.run).parameters) == ["args"]
assert module.run.__globals__ is module.__dict__
for key in ("TDX_ROOT", "DATA_ROOT", "RUN_DIR"):
    value = object()
    setattr(module, key, value)
    assert module.run.__globals__[key] is value
print("PASS_NON_PRODUCING_LOADER_BOUNDARY")
"""
    env = dict(os.environ)
    env.update(
        {
            "PANEL_OLD_APP_ROOT": str(OLD_APP_ROOT),
            "PANEL_FIXED_ENTRY": str(fixed),
            "PANEL_COMPONENT_ROOT": str(component),
        }
    )
    if expect_failure:
        env["PANEL_EXPECT_FAILURE"] = "1"
    return subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _ledger_receipt(claim: dict[str, object], *, status: str = "SUCCEEDED") -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "v3_5.dispatch.v1",
        "run_id": claim["run_id"],
        "scheduled_date": claim["scheduled_date"],
        "business_date": claim["business_date"],
        "target_date": claim["target_date"],
        "slot": claim["slot"],
        "mode": claim["mode"],
        "selected_workload_ids": [overlay.WORKLOAD_ID],
        "started_workload_ids": [overlay.WORKLOAD_ID] if status == "SUCCEEDED" else [],
        "receipt_path": (
            f"receipts/live/{claim['business_date']}/{claim['slot']}/"
            f"{claim['run_id']}.dispatch-receipt.json"
        ),
        "finished_at": "2026-10-23T09:00:00Z",
        "status": status,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    body = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    receipt["ledger_sha256"] = hashlib.sha256(body).hexdigest()
    return receipt


def _bind_test_ledger(monkeypatch: pytest.MonkeyPatch, ledger: Path) -> None:
    """Give a test an explicit fixture ledger without touching the production path."""
    monkeypatch.setattr(overlay, "DISPATCH_LEDGER_ROOT", ledger)


def _claim_fixture(ledger: Path, business_date: str, *, run_id: str = "old-run") -> tuple[Path, Path, dict[str, object]]:
    claim: dict[str, object] = {
        "schema_version": "v3_5.workload_claim.v1",
        "run_id": run_id,
        "workload_id": overlay.WORKLOAD_ID,
        "scheduled_date": business_date,
        "business_date": business_date,
        "target_date": business_date,
        "slot": "1700",
        "mode": "LIVE",
        "pid": 99999999,
    }
    workload = ledger / "workloads" / "live" / business_date / "1700" / f"{overlay.WORKLOAD_ID}.workload-claim.json"
    workload.parent.mkdir(parents=True)
    workload.write_text(json.dumps(claim), encoding="utf-8")
    dispatch_claim = dict(claim)
    dispatch_claim["schema_version"] = "v3_5.dispatch_claim.v1"
    dispatch_claim.pop("workload_id")
    dispatch = ledger / "claims" / "live" / business_date / "1700" / "dispatch.claim.json"
    dispatch.parent.mkdir(parents=True)
    dispatch.write_text(json.dumps(dispatch_claim), encoding="utf-8")
    receipt = ledger / "receipts" / "live" / business_date / "1700" / f"{run_id}.dispatch-receipt.json"
    return workload, dispatch, {"claim": claim, "dispatch_claim": dispatch_claim, "receipt": receipt}


def test_component_has_only_the_14_frozen_pins_and_exact_preimage(tmp_path: Path) -> None:
    candidate = _prepare_fixture(tmp_path)
    root = candidate["component"]
    result = candidate["result"]
    assert isinstance(root, Path) and isinstance(result, dict)
    assert result["status"] == "CANDIDATE_PREPARED_INACTIVE"
    assert result["fixed_entrypoint_still_preimage"] is True
    assert overlay.verify_component(root) == result["component_manifest_sha256"]
    manifest = json.loads((root / "component-manifest.json").read_text(encoding="utf-8"))
    assert manifest["file_count"] == 14
    assert len(manifest["files"]) == 14
    assert (root / "preimage" / "a_share_daily_sync.py").read_bytes() == _read(overlay.FIXED_ENTRYPOINT)


def test_original_loader_fresh_process_keeps_same_module_globals_namespace_and_mac_protocol(tmp_path: Path) -> None:
    candidate = _prepare_fixture(tmp_path)
    fixed = candidate["fixed"]
    component = candidate["component"]
    assert isinstance(fixed, Path) and isinstance(component, Path)
    _install_test_shim(candidate)
    result = _run_loader_process(fixed, component)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "PASS_NON_PRODUCING_LOADER_BOUNDARY" in result.stdout


@pytest.mark.parametrize("tamper", ["manifest", "pinned_file"])
def test_bridge_fails_closed_on_component_manifest_or_pin_tamper(tmp_path: Path, tamper: str) -> None:
    candidate = _prepare_fixture(tmp_path)
    fixed = candidate["fixed"]
    component = candidate["component"]
    assert isinstance(fixed, Path) and isinstance(component, Path)
    _install_test_shim(candidate)
    if tamper == "manifest":
        path = component / "component-manifest.json"
    else:
        path = component / "ops" / "_a_share_daily_sync_parts" / "cli_runtime.py"
    path.write_bytes(path.read_bytes() + b"\n# drift\n")
    result = _run_loader_process(fixed, component, expect_failure=True)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "SHA mismatch" in result.stdout or "pin mismatch" in result.stdout


def test_activation_rejects_non_preimage_fixed_entry_and_preserves_unknown_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = _prepare_fixture(tmp_path)
    fixed = candidate["fixed"]
    component = candidate["component"]
    base_manifest = candidate["base_manifest"]
    assert isinstance(fixed, Path) and isinstance(component, Path) and isinstance(base_manifest, Path)
    fixed.write_bytes(b"unknown preimage")
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    _bind_test_ledger(monkeypatch, ledger)
    with pytest.raises(overlay.OverlayError, match="original preimage"):
        overlay.install_fixed_entrypoint(
            component,
            fixed_entry_path=fixed,
            base_release_manifest_path=base_manifest,
            ledger_root=ledger,
            review_pass_verified=True,
            manual_run_terminal_verified=True,
            now=datetime(2026, 10, 24, 16, 30, tzinfo=SHANGHAI),
            process_rows=[],
        )
    assert fixed.read_bytes() == b"unknown preimage"


def test_activation_rejects_active_child_unfinished_claim_and_1700_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = _prepare_fixture(tmp_path)
    fixed = candidate["fixed"]
    component = candidate["component"]
    base_manifest = candidate["base_manifest"]
    assert isinstance(fixed, Path) and isinstance(component, Path) and isinstance(base_manifest, Path)
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    _bind_test_ledger(monkeypatch, ledger)
    common = {
        "component_root": component,
        "fixed_entry_path": fixed,
        "base_release_manifest_path": base_manifest,
        "ledger_root": ledger,
        "review_pass_verified": True,
        "manual_run_terminal_verified": True,
        "now": datetime(2026, 10, 24, 16, 30, tzinfo=SHANGHAI),
    }
    wrong_ledger = tmp_path / "wrong-ledger"
    wrong_ledger.mkdir()
    with pytest.raises(overlay.OverlayError, match="does not match the configured V3.5 dispatcher ledger"):
        overlay.install_fixed_entrypoint(
            **{**common, "ledger_root": wrong_ledger},
            process_rows=[],
        )

    active_row = [f"4242 /usr/bin/python {fixed}"]
    with pytest.raises(overlay.OverlayError, match="active A child"):
        overlay.install_fixed_entrypoint(**common, process_rows=active_row)

    scheduled_a_row = [
        "4243 /usr/bin/python -m ops.macos_research_panel_daily --date 20261024 --lane A"
    ]
    with pytest.raises(overlay.OverlayError, match="active A child"):
        overlay.install_fixed_entrypoint(**common, process_rows=scheduled_a_row)

    _claim_fixture(ledger, "20261024", run_id="unfinished")
    with pytest.raises(overlay.OverlayError, match="unfinished same-owner"):
        overlay.install_fixed_entrypoint(**common, process_rows=[])

    clean_ledger = tmp_path / "clean-ledger"
    clean_ledger.mkdir()
    _bind_test_ledger(monkeypatch, clean_ledger)
    with pytest.raises(overlay.OverlayError, match="pre-1700"):
        overlay.install_fixed_entrypoint(
            **{**common, "ledger_root": clean_ledger, "now": datetime(2026, 10, 24, 17, 0, tzinfo=SHANGHAI)},
            process_rows=[],
        )


@pytest.mark.parametrize("status", ["SUCCEEDED", "FAILED"])
def test_native_terminal_historical_claims_remain_and_do_not_block_install_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    _bind_test_ledger(monkeypatch, ledger)
    workload_path, dispatch_path, records = _claim_fixture(ledger, "20261023", run_id="completed-run")
    receipt_path = records["receipt"]
    assert isinstance(receipt_path, Path)
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(_ledger_receipt(records["claim"], status=status)), encoding="utf-8")
    before = (workload_path.read_bytes(), dispatch_path.read_bytes())
    overlay.assert_same_owner_idle(
        ledger,
        now=datetime(2026, 10, 24, 16, 30, tzinfo=SHANGHAI),
        pid_alive=lambda _pid: True,
    )
    assert (workload_path.read_bytes(), dispatch_path.read_bytes()) == before


def test_historical_orphan_dispatch_claim_blocks_until_terminal_receipt_without_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    _bind_test_ledger(monkeypatch, ledger)
    workload_path, dispatch_path, records = _claim_fixture(ledger, "20261023", run_id="orphan-run")
    workload_path.unlink()
    with pytest.raises(overlay.OverlayError, match="unfinished same-owner A dispatch claim"):
        overlay.assert_same_owner_idle(
            ledger,
            now=datetime(2026, 10, 24, 16, 30, tzinfo=SHANGHAI),
            pid_alive=lambda _pid: False,
        )

    receipt_path = records["receipt"]
    assert isinstance(receipt_path, Path)
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(_ledger_receipt(records["claim"])), encoding="utf-8")
    dispatch_before = dispatch_path.read_bytes()
    overlay.assert_same_owner_idle(
        ledger,
        now=datetime(2026, 10, 24, 16, 30, tzinfo=SHANGHAI),
        pid_alive=lambda _pid: True,
    )
    assert dispatch_path.read_bytes() == dispatch_before
    assert dispatch_path.is_file()


def test_atomic_candidate_install_and_clean_rollback_preserve_release_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = _prepare_fixture(tmp_path)
    fixed = candidate["fixed"]
    component = candidate["component"]
    base_manifest = candidate["base_manifest"]
    evidence = candidate["evidence"]
    assert all(isinstance(item, Path) for item in (fixed, component, base_manifest, evidence))
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    _bind_test_ledger(monkeypatch, ledger)
    original_manifest = base_manifest.read_bytes()
    original_entry = fixed.read_bytes()
    shim = (evidence / "entrypoint-shim.py").read_bytes()
    installed_sha = overlay.install_fixed_entrypoint(
        component,
        fixed_entry_path=fixed,
        base_release_manifest_path=base_manifest,
        shim_path=evidence / "entrypoint-shim.py",
        ledger_root=ledger,
        review_pass_verified=True,
        manual_run_terminal_verified=True,
        now=datetime(2026, 10, 24, 16, 30, tzinfo=SHANGHAI),
        process_rows=[],
    )
    assert hashlib.sha256(shim).hexdigest() == installed_sha
    assert fixed.read_bytes() == shim
    assert base_manifest.read_bytes() == original_manifest
    assert overlay.restore_preimage(
        component,
        fixed_entry_path=fixed,
        base_release_manifest_path=base_manifest,
        ledger_root=ledger,
        now=datetime(2026, 10, 24, 16, 30, tzinfo=SHANGHAI),
        process_rows=[],
    ) == overlay.BASE_FIXED_ENTRY_SHA256
    assert fixed.read_bytes() == original_entry
    assert base_manifest.read_bytes() == original_manifest
    assert (component / "overlay-manifest.json").is_file()


def test_rollback_refuses_unknown_postimage_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = _prepare_fixture(tmp_path)
    fixed = candidate["fixed"]
    component = candidate["component"]
    base_manifest = candidate["base_manifest"]
    assert isinstance(fixed, Path) and isinstance(component, Path) and isinstance(base_manifest, Path)
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    _bind_test_ledger(monkeypatch, ledger)
    fixed.write_bytes(b"unknown postimage")
    with pytest.raises(overlay.OverlayError, match="preimage CAS failed"):
        overlay.restore_preimage(
            component,
            fixed_entry_path=fixed,
            base_release_manifest_path=base_manifest,
            ledger_root=ledger,
            now=datetime(2026, 10, 24, 16, 30, tzinfo=SHANGHAI),
            process_rows=[],
        )
    assert fixed.read_bytes() == b"unknown postimage"


@pytest.mark.parametrize("status", ["RUNNING", "STARTED", "UNKNOWN_NATIVE_STATUS"])
def test_nonterminal_or_unknown_receipt_cannot_unlock_live_dispatch_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    _bind_test_ledger(monkeypatch, ledger)
    workload_path, dispatch_path, records = _claim_fixture(ledger, "20261023", run_id="not-terminal")
    workload_path.unlink()
    receipt_path = records["receipt"]
    assert isinstance(receipt_path, Path)
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(_ledger_receipt(records["claim"], status=status)), encoding="utf-8")
    with pytest.raises(overlay.OverlayError, match="unfinished same-owner A dispatch claim"):
        overlay.assert_same_owner_idle(
            ledger,
            now=datetime(2026, 10, 24, 16, 30, tzinfo=SHANGHAI),
            pid_alive=lambda _pid: True,
        )
    assert dispatch_path.is_file()


@pytest.mark.parametrize(
    "identity_field,wrong_value",
    [
        ("schema_version", "v3_5.dispatch.unrecognized"),
        ("business_date", "20261022"),
        ("receipt_path", "receipts/live/elsewhere/1700/wrong.dispatch-receipt.json"),
        ("selected_workload_ids", ["research_panel_daily_hk"]),
    ],
)
def test_terminal_receipt_with_wrong_native_identity_does_not_unlock_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    identity_field: str,
    wrong_value: object,
) -> None:
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    _bind_test_ledger(monkeypatch, ledger)
    workload_path, dispatch_path, records = _claim_fixture(ledger, "20261023", run_id="wrong-receipt-identity")
    workload_path.unlink()
    receipt_path = records["receipt"]
    assert isinstance(receipt_path, Path)
    receipt_path.parent.mkdir(parents=True)
    receipt = _ledger_receipt(records["claim"])
    receipt[identity_field] = wrong_value
    body = {key: value for key, value in receipt.items() if key != "ledger_sha256"}
    receipt["ledger_sha256"] = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(overlay.OverlayError, match="unfinished same-owner A dispatch claim"):
        overlay.assert_same_owner_idle(
            ledger,
            now=datetime(2026, 10, 24, 16, 30, tzinfo=SHANGHAI),
            pid_alive=lambda _pid: True,
        )
    assert dispatch_path.is_file()


@pytest.mark.parametrize("gate", ["active_child", "unfinished_claim", "due_window"])
def test_rollback_requires_idle_window_and_ledger_gates_before_cas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gate: str
) -> None:
    candidate = _prepare_fixture(tmp_path)
    fixed = candidate["fixed"]
    component = candidate["component"]
    base_manifest = candidate["base_manifest"]
    assert isinstance(fixed, Path) and isinstance(component, Path) and isinstance(base_manifest, Path)
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    _bind_test_ledger(monkeypatch, ledger)
    shim = _install_test_shim(candidate)
    before = fixed.read_bytes()
    now = datetime(2026, 10, 24, 16, 30, tzinfo=SHANGHAI)
    process_rows: list[str] = []
    if gate == "active_child":
        process_rows = [
            "4242 /usr/bin/python -m ops.macos_research_panel_daily --date 20261024 --lane A"
        ]
    elif gate == "unfinished_claim":
        _claim_fixture(ledger, "20261023", run_id="rollback-running")
    else:
        now = datetime(2026, 10, 24, 17, 0, tzinfo=SHANGHAI)
    reason = (
        "active A child"
        if gate == "active_child"
        else "unfinished same-owner"
        if gate == "unfinished_claim"
        else "pre-1700"
    )
    with pytest.raises(overlay.OverlayError, match=reason):
        overlay.restore_preimage(
            component,
            fixed_entry_path=fixed,
            base_release_manifest_path=base_manifest,
            ledger_root=ledger,
            now=now,
            process_rows=process_rows,
        )
    assert fixed.read_bytes() == before == shim


def test_rollback_cli_rejects_unbound_ledger_before_candidate_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bound = tmp_path / "bound-ledger"
    wrong = tmp_path / "wrong-ledger"
    bound.mkdir()
    wrong.mkdir()
    _bind_test_ledger(monkeypatch, bound)
    with pytest.raises(overlay.OverlayError, match="does not match the configured V3.5 dispatcher ledger"):
        overlay.main(
            [
                "rollback",
                "--ledger-root",
                str(wrong),
                "--acknowledge-controller-release",
            ]
        )
