"""Behavior contracts for the seven fixed shared stage owners."""
from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
import scripts.run_scheduled_stage_bundle as stage_runner

from scripts.run_scheduled_stage_bundle import (
    SCHEDULED_STAGE_SPECS,
    _trusted_universe_inputs,
    run_scheduled_stage_bundle,
    seconds_until_cutoff,
)


EXPECTED_SPECS = (
    ("V3Shared_Acquire_STAGE_0930_0935", "STAGE_0930_0935", "09:35"),
    ("V3Shared_Acquire_STAGE_0935_0940", "STAGE_0935_0940", "09:40"),
    ("V3Shared_Acquire_STAGE_0940_0945", "STAGE_0940_0945", "09:45"),
    ("V3Shared_Acquire_STAGE_0945_1030", "STAGE_0945_1030", "10:30"),
    ("V3Shared_Acquire_STAGE_1300_1315", "STAGE_1300_1315", "13:15"),
    ("V3Shared_Acquire_STAGE_1445_1500", "STAGE_1445_1500", "15:00"),
    ("V3Shared_Acquire_STAGE_1545_1555", "STAGE_1545_1555", "15:55"),
)


def _ready_universe_runner(*_args):
    return {
        "ok": True,
        "status": "READY",
        "run_id": "universe-test",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _isolated_trusted_inputs(monkeypatch, tmp_path, *, outside_panel: bool = False, bom: bool = False):
    project_root = tmp_path / "v3_shared_data"
    v35_root = tmp_path / "v3.5" / ".runtime" / "data"
    selector_root = tmp_path / "数据" / "selector_ready_panels"
    pointer = tmp_path / "数据" / "data_layer_interface_current" / "CURRENT_SELECTOR_READY_PANEL.txt"
    project_root.mkdir(parents=True)
    v35_root.mkdir(parents=True)
    selector_root.mkdir(parents=True)
    panel = (tmp_path / "outside.parquet") if outside_panel else (selector_root / "selector.parquet")
    panel.write_bytes(b"selector")
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_bytes((str(panel) + "\n").encode("utf-8-sig" if bom else "utf-8"))
    monkeypatch.setattr(stage_runner, "_PROJECT_ROOT", project_root)
    for name in (
        "V35_DATA_ROOT",
        "V3_SHARED_SELECTOR_READY_PANEL_POINTER",
        "V3_SHARED_SELECTOR_READY_PANEL",
    ):
        monkeypatch.delenv(name, raising=False)
    return v35_root, pointer, panel


def test_trusted_universe_inputs_rejects_v35_root_override(monkeypatch, tmp_path) -> None:
    _isolated_trusted_inputs(monkeypatch, tmp_path)
    override_root = tmp_path / "v35-override"
    override_root.mkdir()
    monkeypatch.setenv("V35_DATA_ROOT", str(override_root))

    with pytest.raises(ValueError, match="V3.5 data root must be the trusted sibling"):
        _trusted_universe_inputs()


def test_trusted_universe_inputs_rejects_selector_panel_outside_trusted_root(
    monkeypatch, tmp_path
) -> None:
    _isolated_trusted_inputs(monkeypatch, tmp_path, outside_panel=True)

    with pytest.raises(ValueError, match="selector-ready target outside trusted root"):
        _trusted_universe_inputs()


def test_trusted_universe_inputs_accepts_utf8_sig_pointer(monkeypatch, tmp_path) -> None:
    _isolated_trusted_inputs(monkeypatch, tmp_path, bom=True)

    _, _, panel = _trusted_universe_inputs()
    assert panel.name == "selector.parquet"


def test_exact_seven_stage_owners_and_times_are_frozen() -> None:
    assert SCHEDULED_STAGE_SPECS == EXPECTED_SPECS


def test_cutoff_wait_covers_the_five_second_stage_boundary() -> None:
    assert seconds_until_cutoff(
        datetime(2026, 8, 10, 9, 35, 0), "STAGE_0930_0935"
    ) == 5.0
    assert seconds_until_cutoff(
        datetime(2026, 8, 10, 9, 35, 6), "STAGE_0930_0935"
    ) == 0.0


def test_early_manual_start_is_not_due_and_never_acquires() -> None:
    calls = 0

    def forbidden_runner(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("pre-cutoff run must not acquire")

    with tempfile.TemporaryDirectory(prefix="v3sd_stage_schedule_") as tmp:
        root = Path(tmp)
        result = run_scheduled_stage_bundle(
            root,
            "20260810",
            "STAGE_0930_0935",
            now=datetime(2026, 8, 10, 9, 34, 0),
            python_path=root / "missing-python-is-unused.exe",
            bundle_runner=forbidden_runner,
        )

        assert result["ok"] is False
        assert result["status"] == "NOT_DUE"
        assert calls == 0
        assert Path(result["receipt_path"]).is_file()


def test_trading_day_runs_one_fixed_bundle_and_writes_safe_receipt() -> None:
    calls: list[tuple[Path, str, str, Path]] = []

    def bundle_runner(root: Path, trade_date: str, stage_id: str, python_path: Path):
        calls.append((root, trade_date, stage_id, python_path))
        return {"ok": True, "status": "READY", "bundle_id": "bundle-1"}

    with tempfile.TemporaryDirectory(prefix="v3sd_stage_schedule_") as tmp:
        root = Path(tmp)
        python_path = root / "python.exe"
        python_path.write_bytes(b"")
        result = run_scheduled_stage_bundle(
            root,
            "20260810",
            "STAGE_0930_0935",
            now=datetime(2026, 8, 10, 9, 35, 6),
            python_path=python_path,
            bundle_runner=bundle_runner,
            universe_runner=_ready_universe_runner,
            security_master_runner=lambda *_args: {
                "ok": True, "status": "READY", "run_id": "master-1"
            },
        )

        assert result["ok"] is True
        assert result["status"] == "READY"
        assert calls == [(root, "20260810", "STAGE_0930_0935", python_path)]
        receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
        assert receipt["bundle"]["bundle_id"] == "bundle-1"
        assert receipt["hk_security_master"]["run_id"] == "master-1"
        assert receipt["production_allowed"] is False
        assert receipt["buy_gate_updated"] is False
        assert receipt["orders_sent"] is False


def test_weekend_is_a_successful_skip_and_never_calls_futu_bundle() -> None:
    calls = 0

    def forbidden_runner(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("weekend must not acquire")

    with tempfile.TemporaryDirectory(prefix="v3sd_stage_schedule_") as tmp:
        root = Path(tmp)
        result = run_scheduled_stage_bundle(
            root,
            "20260809",
            "STAGE_0930_0935",
            now=datetime(2026, 8, 9, 9, 35, 6),
            python_path=root / "missing-python-is-unused.exe",
            bundle_runner=forbidden_runner,
        )

        assert result["ok"] is True
        assert result["status"] == "SKIPPED_NON_TRADING_DAY"
        assert calls == 0
        assert Path(result["receipt_path"]).is_file()


def test_bundle_failure_returns_nonzero_semantics_and_persists_receipt() -> None:
    def failed_runner(*_args, **_kwargs):
        raise OSError("OpenD unavailable")

    with tempfile.TemporaryDirectory(prefix="v3sd_stage_schedule_") as tmp:
        root = Path(tmp)
        python_path = root / "python.exe"
        python_path.write_bytes(b"")
        result = run_scheduled_stage_bundle(
            root,
            "20260810",
            "STAGE_0930_0935",
            now=datetime(2026, 8, 10, 9, 35, 6),
            python_path=python_path,
            bundle_runner=failed_runner,
            universe_runner=_ready_universe_runner,
            security_master_runner=lambda *_args: {
                "ok": True, "status": "READY", "run_id": "master-1"
            },
        )

        assert result["ok"] is False
        assert result["status"] == "FAILED"
        assert result["error"] == "OpenD unavailable"
        assert Path(result["receipt_path"]).is_file()


def test_universe_preflight_runs_before_security_master_and_bundle() -> None:
    events: list[str] = []

    def universe_runner(root: Path, trade_date: str):
        events.append(f"universe:{trade_date}")
        return {
            "ok": True,
            "status": "READY",
            "run_id": "universe-1",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def security_master_runner(*_args):
        events.append("security-master")
        return {"ok": True, "status": "READY", "run_id": "master-1"}

    def bundle_runner(*_args, **_kwargs):
        events.append("bundle")
        return {"ok": True, "status": "READY", "bundle_id": "bundle-1"}

    with tempfile.TemporaryDirectory(prefix="v3sd_stage_schedule_") as tmp:
        root = Path(tmp)
        python_path = root / "python.exe"
        python_path.write_bytes(b"")
        result = run_scheduled_stage_bundle(
            root,
            "20260810",
            "STAGE_0930_0935",
            now=datetime(2026, 8, 10, 9, 35, 6),
            python_path=python_path,
            universe_runner=universe_runner,
            security_master_runner=security_master_runner,
            bundle_runner=bundle_runner,
        )

        assert result["ok"] is True
        assert events == ["universe:20260810", "security-master", "bundle"]
        assert result["universe_preflight"]["run_id"] == "universe-1"
        stored = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
        assert stored["universe_preflight"]["status"] == "READY"


def test_universe_preflight_failure_is_fail_closed_before_market_calls() -> None:
    events: list[str] = []

    def universe_runner(*_args):
        events.append("universe")
        return {"ok": False, "status": "FAILED", "error": "selector-ready panel missing"}

    def forbidden_security_master(*_args):
        events.append("security-master")
        raise AssertionError("security master must not run after universe preflight failure")

    def forbidden_bundle(*_args, **_kwargs):
        events.append("bundle")
        raise AssertionError("stage bundle must not run after universe preflight failure")

    with tempfile.TemporaryDirectory(prefix="v3sd_stage_schedule_") as tmp:
        root = Path(tmp)
        python_path = root / "python.exe"
        python_path.write_bytes(b"")
        result = run_scheduled_stage_bundle(
            root,
            "20260810",
            "STAGE_0930_0935",
            now=datetime(2026, 8, 10, 9, 35, 6),
            python_path=python_path,
            universe_runner=universe_runner,
            security_master_runner=forbidden_security_master,
            bundle_runner=forbidden_bundle,
        )

        assert result["ok"] is False
        assert result["status"] == "FAILED"
        assert result["attempts"] == 0
        assert events == ["universe"]
        assert "selector-ready panel missing" in result["error"]
        assert result["universe_preflight"]["status"] == "FAILED"
        stored = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
        assert stored["bundle"] is None
        assert stored["hk_security_master"] is None


@pytest.mark.parametrize(
    "safety_flag",
    ("production_allowed", "buy_gate_updated", "orders_sent"),
)
def test_universe_preflight_safety_flags_must_be_false(
    safety_flag: str,
) -> None:
    events: list[str] = []

    def universe_runner(*_args):
        events.append("universe")
        return {
            "ok": True,
            "status": "READY",
            "run_id": "universe-unsafe",
            "production_allowed": safety_flag == "production_allowed",
            "buy_gate_updated": safety_flag == "buy_gate_updated",
            "orders_sent": safety_flag == "orders_sent",
        }

    def forbidden_security_master(*_args):
        events.append("security-master")
        raise AssertionError("security master must not run after unsafe preflight")

    def forbidden_bundle(*_args, **_kwargs):
        events.append("bundle")
        raise AssertionError("bundle must not run after unsafe preflight")

    with tempfile.TemporaryDirectory(prefix="v3sd_stage_schedule_") as tmp:
        root = Path(tmp)
        python_path = root / "python.exe"
        python_path.write_bytes(b"")
        result = run_scheduled_stage_bundle(
            root,
            "20260810",
            "STAGE_0930_0935",
            now=datetime(2026, 8, 10, 9, 35, 6),
            python_path=python_path,
            universe_runner=universe_runner,
            security_master_runner=forbidden_security_master,
            bundle_runner=forbidden_bundle,
        )

        assert result["ok"] is False
        assert result["attempts"] == 0
        assert events == ["universe"]
        assert safety_flag in result["error"]


def test_transient_transport_result_is_retried_with_bounded_injected_backoff() -> None:
    bundle_calls = 0
    sleeps: list[float] = []

    def bundle_runner(*_args, **_kwargs):
        nonlocal bundle_calls
        bundle_calls += 1
        if bundle_calls == 1:
            return {
                "ok": False,
                "status": "FAILED",
                "error": "incomplete shared markets: A_SHARE",
                "markets": {
                    "A_SHARE": {
                        "status": "FAILED",
                        "error": "futu bridge: OpenD unavailable",
                    }
                },
            }
        return {"ok": True, "status": "READY", "bundle_id": "bundle-retry"}

    with tempfile.TemporaryDirectory(prefix="v3sd_stage_schedule_") as tmp:
        root = Path(tmp)
        python_path = root / "python.exe"
        python_path.write_bytes(b"")
        result = run_scheduled_stage_bundle(
            root,
            "20260810",
            "STAGE_0930_0935",
            now=datetime(2026, 8, 10, 9, 35, 6),
            python_path=python_path,
            bundle_runner=bundle_runner,
            universe_runner=_ready_universe_runner,
            security_master_runner=lambda *_args: {"ok": True, "status": "READY"},
            max_attempts=2,
            retry_backoff_seconds=0.25,
            sleep_fn=sleeps.append,
        )

        assert result["ok"] is True
        assert result["status"] == "READY"
        assert result["attempts"] == 2
        assert bundle_calls == 2
        assert sleeps == [0.25]
        stored = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
        assert stored["attempts"] == 2


def test_nontransient_bundle_failure_is_not_retried() -> None:
    bundle_calls = 0
    sleeps: list[float] = []

    def bundle_runner(*_args, **_kwargs):
        nonlocal bundle_calls
        bundle_calls += 1
        return {
            "ok": False,
            "status": "FAILED",
            "error": "incomplete shared markets: A_SHARE",
            "markets": {
                "A_SHARE": {
                    "status": "FAILED",
                    "error": "futu returned no rows before cutoff",
                }
            },
        }

    with tempfile.TemporaryDirectory(prefix="v3sd_stage_schedule_") as tmp:
        root = Path(tmp)
        python_path = root / "python.exe"
        python_path.write_bytes(b"")
        result = run_scheduled_stage_bundle(
            root,
            "20260810",
            "STAGE_0930_0935",
            now=datetime(2026, 8, 10, 9, 35, 6),
            python_path=python_path,
            bundle_runner=bundle_runner,
            universe_runner=_ready_universe_runner,
            security_master_runner=lambda *_args: {"ok": True, "status": "READY"},
            max_attempts=3,
            retry_backoff_seconds=0.25,
            sleep_fn=sleeps.append,
        )

        assert result["ok"] is False
        assert result["status"] == "FAILED"
        assert result["attempts"] == 1
        assert bundle_calls == 1
        assert sleeps == []


def test_generic_semantic_timeout_marker_is_not_retried() -> None:
    bundle_calls = 0

    def bundle_runner(*_args, **_kwargs):
        nonlocal bundle_calls
        bundle_calls += 1
        return {
            "ok": False,
            "status": "FAILED",
            "error": "coverage timeout: exact cutoff evidence missing",
        }

    with tempfile.TemporaryDirectory(prefix="v3sd_stage_schedule_") as tmp:
        root = Path(tmp)
        python_path = root / "python.exe"
        python_path.write_bytes(b"")
        result = run_scheduled_stage_bundle(
            root,
            "20260810",
            "STAGE_0930_0935",
            now=datetime(2026, 8, 10, 9, 35, 6),
            python_path=python_path,
            bundle_runner=bundle_runner,
            universe_runner=_ready_universe_runner,
            security_master_runner=lambda *_args: {"ok": True, "status": "READY"},
            max_attempts=3,
            sleep_fn=lambda _seconds: (_ for _ in ()).throw(AssertionError("must not sleep")),
        )

        assert result["ok"] is False
        assert result["attempts"] == 1
        assert bundle_calls == 1


def test_typed_filesystem_failure_is_not_retried() -> None:
    bundle_calls = 0

    def bundle_runner(*_args, **_kwargs):
        nonlocal bundle_calls
        bundle_calls += 1
        raise FileNotFoundError("missing verified universe")

    with tempfile.TemporaryDirectory(prefix="v3sd_stage_schedule_") as tmp:
        root = Path(tmp)
        python_path = root / "python.exe"
        python_path.write_bytes(b"")
        result = run_scheduled_stage_bundle(
            root,
            "20260810",
            "STAGE_0930_0935",
            now=datetime(2026, 8, 10, 9, 35, 6),
            python_path=python_path,
            bundle_runner=bundle_runner,
            universe_runner=_ready_universe_runner,
            security_master_runner=lambda *_args: {"ok": True, "status": "READY"},
            max_attempts=3,
            sleep_fn=lambda _seconds: (_ for _ in ()).throw(AssertionError("must not sleep")),
        )

        assert result["ok"] is False
        assert result["status"] == "FAILED"
        assert result["attempts"] == 1
        assert bundle_calls == 1


def test_value_error_is_never_retried_even_with_transport_words() -> None:
    bundle_calls = 0

    def bundle_runner(*_args, **_kwargs):
        nonlocal bundle_calls
        bundle_calls += 1
        raise ValueError("futu bridge: OpenD unavailable")

    with tempfile.TemporaryDirectory(prefix="v3sd_stage_schedule_") as tmp:
        root = Path(tmp)
        python_path = root / "python.exe"
        python_path.write_bytes(b"")
        result = run_scheduled_stage_bundle(
            root,
            "20260810",
            "STAGE_0930_0935",
            now=datetime(2026, 8, 10, 9, 35, 6),
            python_path=python_path,
            bundle_runner=bundle_runner,
            universe_runner=_ready_universe_runner,
            security_master_runner=lambda *_args: {"ok": True, "status": "READY"},
            max_attempts=3,
            sleep_fn=lambda _seconds: (_ for _ in ()).throw(AssertionError("must not sleep")),
        )

        assert result["ok"] is False
        assert result["attempts"] == 1
        assert bundle_calls == 1


def test_security_master_timeout_is_retried_before_bundle() -> None:
    master_calls = 0
    bundle_calls = 0
    sleeps: list[float] = []

    def security_master_runner(*_args):
        nonlocal master_calls
        master_calls += 1
        if master_calls == 1:
            raise TimeoutError("OpenD timed out")
        return {"ok": True, "status": "READY", "run_id": "master-retry"}

    def bundle_runner(*_args, **_kwargs):
        nonlocal bundle_calls
        bundle_calls += 1
        return {"ok": True, "status": "READY", "bundle_id": "bundle-after-master"}

    with tempfile.TemporaryDirectory(prefix="v3sd_stage_schedule_") as tmp:
        root = Path(tmp)
        python_path = root / "python.exe"
        python_path.write_bytes(b"")
        result = run_scheduled_stage_bundle(
            root,
            "20260810",
            "STAGE_0930_0935",
            now=datetime(2026, 8, 10, 9, 35, 6),
            python_path=python_path,
            bundle_runner=bundle_runner,
            universe_runner=_ready_universe_runner,
            security_master_runner=security_master_runner,
            max_attempts=2,
            retry_backoff_seconds=0.5,
            sleep_fn=sleeps.append,
        )

        assert result["ok"] is True
        assert result["attempts"] == 2
        assert master_calls == 2
        assert bundle_calls == 1
        assert sleeps == [0.5]


def test_registration_describe_only_emits_fixed_non_overlapping_actions() -> None:
    project_root = Path(__file__).resolve().parents[1]
    script = project_root / "_ops" / "register_v3_shared_stage_tasks.ps1"
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-DescribeOnly",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    described = json.loads(completed.stdout)
    assert len(described) == 8
    auction = described[0]
    assert (auction["TaskName"], auction["StageId"], auction["At"]) == (
        "V3Shared_Acquire_HK_AUCTION_0920", "HK_AUCTION_0920", "09:15"
    )
    assert "run_hk_auction_0920.ps1" in auction["Arguments"]
    assert "-StageId" not in auction["Arguments"]
    assert [
        (item["TaskName"], item["StageId"], item["At"])
        for item in described[1:]
    ] == list(EXPECTED_SPECS)
    for item in described:
        assert item["TaskPath"] == "\\V3Shared\\"
        assert item["Execute"] == "powershell.exe"
        assert item["MultipleInstances"] == "IgnoreNew"
    for item in described[1:]:
        assert "run_stage_bundle.ps1" in item["Arguments"]
        assert f'-StageId {item["StageId"]}' in item["Arguments"]


def test_stage_launcher_is_ascii_safe_for_windows_powershell_51() -> None:
    project_root = Path(__file__).resolve().parents[1]
    launcher = project_root / "_ops" / "run_stage_bundle.ps1"

    raw = launcher.read_bytes()

    assert all(byte < 128 for byte in raw), (
        "Windows PowerShell 5.1 decodes UTF-8 without a BOM as the active ANSI "
        "code page; the scheduled launcher must stay ASCII-safe"
    )
