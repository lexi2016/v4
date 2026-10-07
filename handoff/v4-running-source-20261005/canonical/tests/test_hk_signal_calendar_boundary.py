from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_hk_price_and_connect_eligibility_dates_remain_separate() -> None:
    from infrastructure.scheduling._executor_registry_parts.preselection import (
        _hk_price_and_eligibility_dates,
    )

    assert _hk_price_and_eligibility_dates("20260928") == (
        "20260925",
        "20260924",
    )
    assert _hk_price_and_eligibility_dates("20260929") == (
        "20260928",
        "20260928",
    )
    assert _hk_price_and_eligibility_dates("20261008") == (
        "20261007",
        "20260930",
    )


@pytest.mark.parametrize(
    ("business_date", "target_date", "price_date", "eligibility_date"),
    [
        ("20260925", "20260928", "20260925", "20260924"),
        ("20261007", "20261008", "20261007", "20260930"),
    ],
)
def test_original_preselection_owner_forwards_split_hk_dates_through_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    business_date: str,
    target_date: str,
    price_date: str,
    eligibility_date: str,
) -> None:
    from contracts.runtime_tasks import DispatchMode, DispatchRequest
    from infrastructure.scheduling import executor_registry as registry_module
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry

    calls: list[tuple[str, list[str]]] = []

    def fake_runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        module = str(command[2])
        arguments = list(command[3:])
        calls.append((module, arguments))
        if module == "ops.materialize_scheduled_preselection":
            market_scope = arguments[arguments.index("--market-scope") + 1]
            payload = {
                "status": "READY",
                "formal_pool_gate": {
                    "status": "READY",
                    "market_scope": market_scope,
                    "required": {
                        "hkconnect_d1_top100": {
                            "status": "STRICT_0_2_READY",
                            "row_count": 100,
                            "ready": True,
                        },
                    },
                },
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        registry_module,
        "load_isolated_package_module",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ModuleNotFoundError("fixture")),
    )
    shared_root = tmp_path / "shared"
    (shared_root / "universes").mkdir(parents=True)
    (shared_root / "assets/hk_security_master").mkdir(parents=True)
    package_root = tmp_path / "package"
    scripts = package_root / "scripts"
    scripts.mkdir(parents=True)
    for name in (
        "capture_public_fupan.py",
        "materialize_v192_selector.py",
        "update_hk_0_2_panel.py",
        "materialize_hk_0_2.py",
    ):
        (scripts / name).write_text("# fixture\n", encoding="utf-8")

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        shared_data_root=shared_root,
        hk_universe_root=shared_root,
        shared_package_root=package_root,
        selector_data_root=tmp_path / "selector",
        preselection_input_root=tmp_path / "input",
        repo_root=Path(__file__).parents[1],
        runner=fake_runner,
        hk_0_2_python_executable=Path(sys.executable),
    )
    monkeypatch.setattr(registry, "_hk_0_2_runtime_error", lambda: None)
    request = DispatchRequest(
        scheduled_date=business_date,
        business_date=business_date,
        target_date=target_date,
        slot="1800",
        mode=DispatchMode.LIVE,
    )

    result = registry._preselection_pools(request)

    assert result["status"] == "SUCCEEDED"
    assert result["a_lane_status"] == "NOT_APPLICABLE"
    assert result["hk_lane_status"] == "SUCCEEDED"
    by_module = {module: arguments for module, arguments in calls}
    update = by_module["scripts.update_hk_0_2_panel"]
    assert update[update.index("--through-date") + 1] == price_date
    security = by_module["ops.ensure_hk_security_master"]
    assert security[security.index("--trade-date") + 1] == eligibility_date
    materialize = by_module["scripts.materialize_hk_0_2"]
    assert materialize[materialize.index("--signal-date") + 1] == price_date
    assert materialize[materialize.index("--eligibility-source-date") + 1] == eligibility_date
    projection = by_module["ops.materialize_scheduled_preselection"]
    assert projection[projection.index("--signal-date") + 1] == business_date
    assert projection[projection.index("--hk-signal-date") + 1] == price_date
    assert projection[projection.index("--hk-eligibility-source-date") + 1] == eligibility_date

    pool = _shared_hk_pool(
        signal_date=price_date,
        target_date=target_date,
        eligibility_date=eligibility_date,
        captured_at=f"{eligibility_date[:4]}-{eligibility_date[4:6]}-{eligibility_date[6:]}T17:20:06+08:00",
    )

    def hk_pool_reader(_root: Path, **kwargs):
        assert kwargs == {
            "target_date": target_date,
            "expected_signal_date": price_date,
            "expected_eligibility_source_date": eligibility_date,
        }
        return pool

    from ops.materialize_scheduled_preselection import main as project_scheduled_artifacts

    projection_exit = project_scheduled_artifacts(
        argv=projection,
        pool_reader=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            FileNotFoundError("A fixture unavailable")
        ),
        hk_pool_reader=hk_pool_reader,
    )
    # The unrelated A formal input is absent in this fixture.  The HK artifact
    # still has to be present with split provenance and pass the real Stage gate.
    assert projection_exit == 0
    from stage_center.runner import _validate_hk_d1

    hk_artifact_path, _ = _validate_hk_d1(tmp_path / "data", target_date)
    assert hk_artifact_path.is_file()


def test_hk_materializer_preserves_existing_split_date_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = (
        Path(__file__).parents[1]
        / "upstreams/v3_shared_data/scripts/materialize_hk_0_2.py"
    )
    spec = importlib.util.spec_from_file_location("materialize_hk_0_2_cli_fixture", script)
    assert spec is not None and spec.loader is not None
    materializer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(materializer)

    store_root = tmp_path / "shared-store"
    store_root.mkdir()
    sentinel = store_root / "existing-target.json"
    sentinel_bytes = b"pre-existing verified target\n"
    sentinel.write_bytes(sentinel_bytes)
    expected = {
        "target_date": "20260928",
        "expected_signal_date": "20260925",
        "expected_eligibility_source_date": "20260924",
    }
    existing = SimpleNamespace(
        run=SimpleNamespace(
            receipt={"status": "READY"},
            verification={
                "run_id": "existing-hk-run",
                "artifact_sha256": "a" * 64,
                "manifest_sha256": "b" * 64,
                "receipt_sha256": "c" * 64,
            },
        )
    )

    def read_existing(root: Path, **kwargs):
        assert root == store_root
        assert kwargs == expected
        return existing

    monkeypatch.setattr(materializer, "read_verified_hk_0_2_pool", read_existing)
    monkeypatch.setattr(
        materializer,
        "materialize_frozen_hk_0_2",
        lambda *_args, **_kwargs: pytest.fail("valid existing HK target must not be rebuilt"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            "--store-root",
            str(store_root),
            "--asset-root",
            str(tmp_path / "assets"),
            "--signal-date",
            expected["expected_signal_date"],
            "--eligibility-source-date",
            expected["expected_eligibility_source_date"],
            "--target-date",
            expected["target_date"],
        ],
    )

    assert materializer.main() == 0
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["already_exists"] is True
    assert outcome["status"] == "READY"
    assert outcome["run_id"] == "existing-hk-run"
    assert sentinel.read_bytes() == sentinel_bytes


def _shared_hk_pool(*, signal_date: str, target_date: str, eligibility_date: str, captured_at: str):
    provenance = {
        "signal_date": signal_date,
        "eligibility_source_date": eligibility_date,
        "security_master_trade_date": eligibility_date,
        "security_master_run_id": "security-master-run-20260924",
        "security_master_artifact_sha256": "d" * 64,
        "security_master_captured_at": captured_at,
    }
    verification = {
        "run_id": "hk-d1-run-20260928",
        "artifact_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        "receipt_sha256": "c" * 64,
        "artifact_relative": "runs/20260928/HK_CONNECT_D1_TOP100_0_2/run/artifact.csv",
        "row_count": 100,
    }
    rows = [
        {
            "rank": index,
            "code": f"HK.{index:05d}",
            "code_norm": f"HK.{index:05d}",
            "name": f"HK company {index}",
            "signal_date": signal_date,
            "target_date": target_date,
            "selected_strategy": "prob_active",
            "d1_freshness_status": "PASS",
            "score_prob_active": 1.0 - index / 1000.0,
        }
        for index in range(1, 101)
    ]
    run = SimpleNamespace(
        receipt={
            "status": "READY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        verification=verification,
        manifest={"provenance": provenance},
    )
    return SimpleNamespace(run=run, rows=rows)


def _project_hk_pool(*, signal_date: str, target_date: str, eligibility_date: str, captured_at: str):
    from domains.preselection_materializer import build_shared_hk_0_2_pool

    pool = _shared_hk_pool(
        signal_date=signal_date,
        target_date=target_date,
        eligibility_date=eligibility_date,
        captured_at=captured_at,
    )
    calls: dict[str, object] = {}

    def reader(_root: Path, **kwargs):
        calls.update(kwargs)
        return pool

    artifact = build_shared_hk_0_2_pool(
        Path("/unused-test-source"),
        trade_date=target_date,
        signal_date=signal_date,
        eligibility_source_date=eligibility_date,
        reader=reader,
    )
    return artifact, calls


def _materialize_and_validate(tmp_path: Path, artifact: dict, trade_date: str) -> str:
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    from stage_center.runner import _validate_hk_d1

    store = PreselectionPoolStore(tmp_path)
    store.materialize(artifact)
    path, digest = _validate_hk_d1(tmp_path, trade_date)
    assert path.is_file()
    return digest


def test_projected_split_date_pool_binds_price_and_eligibility_sources(tmp_path: Path) -> None:
    artifact, calls = _project_hk_pool(
        signal_date="20260925",
        target_date="20260928",
        eligibility_date="20260924",
        captured_at="2026-09-24T17:20:06+08:00",
    )

    assert calls == {
        "target_date": "20260928",
        "expected_signal_date": "20260925",
        "expected_eligibility_source_date": "20260924",
    }
    history = artifact["historical_provenance"]
    assert history["price_signal_date"] == "20260925"
    assert history["eligibility_source_date"] == "20260924"
    assert history["eligibility_source_captured_at"] == "2026-09-24T17:20:06+08:00"
    assert history["d1_source_run_id"] == artifact["source_run_id"]
    assert artifact["stage_selection_eligible"] is True
    _materialize_and_validate(tmp_path, artifact, "20260928")


def test_scheduled_projection_passes_distinct_hk_price_and_eligibility_dates(
    tmp_path: Path,
) -> None:
    from ops.materialize_scheduled_preselection import build_scheduled_artifacts

    calls: dict[str, object] = {}
    pool = _shared_hk_pool(
        signal_date="20260925",
        target_date="20260928",
        eligibility_date="20260924",
        captured_at="2026-09-24T17:20:06+08:00",
    )

    def hk_reader(_root: Path, **kwargs):
        calls.update(kwargs)
        return pool

    artifacts = build_scheduled_artifacts(
        trade_date="20260928",
        signal_date="20260924",
        hk_signal_date="20260925",
        selector=None,
        input_root=tmp_path / "input",
        shared_data_root=tmp_path / "shared",
        shared_package_root=tmp_path / "package",
        data_root=tmp_path / "data",
        pool_reader=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            FileNotFoundError("A fixture unavailable")
        ),
        hk_pool_reader=hk_reader,
    )

    assert calls == {
        "target_date": "20260928",
        "expected_signal_date": "20260925",
        "expected_eligibility_source_date": "20260924",
    }
    by_id = {artifact["pool_id"]: artifact for artifact in artifacts}
    assert by_id["hkconnect_d1_top100"]["signal_date"] == "20260925"
    assert by_id["hkconnect_d1_top100"]["historical_provenance"][
        "eligibility_source_date"
    ] == "20260924"


def test_projection_preserves_legacy_same_date_call_shape(tmp_path: Path) -> None:
    artifact, calls = _project_hk_pool(
        signal_date="20260928",
        target_date="20260929",
        eligibility_date="20260928",
        captured_at="2026-09-28T17:20:06+08:00",
    )

    assert calls == {
        "target_date": "20260929",
        "expected_signal_date": "20260928",
    }
    assert "historical_provenance" not in artifact
    _materialize_and_validate(tmp_path, artifact, "20260929")


def test_stage_rejects_misdated_928_price_rows(tmp_path: Path) -> None:
    from stage_center.runner import RunnerError

    artifact, _calls = _project_hk_pool(
        signal_date="20260924",
        target_date="20260928",
        eligibility_date="20260924",
        captured_at="2026-09-24T17:20:06+08:00",
    )

    with pytest.raises(RunnerError, match="signal_date"):
        _materialize_and_validate(tmp_path, artifact, "20260928")


def test_stage_rejects_late_captured_eligibility_master(tmp_path: Path) -> None:
    from stage_center.runner import RunnerError

    artifact, _calls = _project_hk_pool(
        signal_date="20260925",
        target_date="20260928",
        eligibility_date="20260924",
        captured_at="2026-09-28T02:50:33+08:00",
    )

    with pytest.raises(RunnerError, match="capture date mismatch"):
        _materialize_and_validate(tmp_path, artifact, "20260928")


@pytest.mark.parametrize("encoded_capture_time", [False, True])
def test_verified_hk_reader_checks_independent_eligibility_master_date(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    encoded_capture_time: bool,
) -> None:
    from upstreams.v3_shared_data.shared_data import hk_0_2

    artifact_path = tmp_path / "artifact.csv"
    fields = (
        "rank",
        "code_norm",
        "name",
        "score_prob_active",
    )
    with artifact_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {
                "rank": index,
                "code_norm": f"HK.{index:05d}",
                "name": f"HK company {index}",
                "score_prob_active": 1.0 - index / 1000.0,
            }
            for index in range(1, 101)
        )

    security_master_manifest = {
        "trade_date": "20260924",
        "run_id": "security-master-run-20260924",
        "artifact_sha256": "d" * 64,
        "captured_at": "2026-09-24T17:20:06+08:00",
    }
    source_provenance = {
        "signal_date": "20260925",
        "eligibility_source_date": "20260924",
        "source_contract": "tdx_vipdoc_71_day_prob_active",
        "model_bundle_sha256": hk_0_2.HK_0_2_MODEL_SHA256,
        "daily_features_sha256": hk_0_2.HK_0_2_ORACLE_SHA256S["daily_features"],
        "proxy_prob_active_sha256": hk_0_2.HK_0_2_ORACLE_SHA256S["proxy_prob_active"],
        "security_master_trade_date": "20260924",
        "security_master_run_id": security_master_manifest["run_id"],
        "security_master_artifact_sha256": security_master_manifest["artifact_sha256"],
        "security_master_captured_at": (
            hk_0_2._encode_capture_at_provenance(
                security_master_manifest["captured_at"]
            )
            if encoded_capture_time
            else security_master_manifest["captured_at"]
        ),
    }
    run = SimpleNamespace(
        manifest={"provenance": source_provenance},
        artifact_path=artifact_path,
    )
    run.verification = {"row_count": 100}
    monkeypatch.setattr(
        hk_0_2,
        "_load_verified_security_master",
        lambda _root, trade_date: (
            {f"HK.{index:05d}": {} for index in range(1, 101)},
            security_master_manifest,
        ),
    )
    monkeypatch.setattr(hk_0_2, "read_verified_latest", lambda *_args: run)

    result = hk_0_2.read_verified_hk_0_2_pool(
        tmp_path,
        target_date="20260928",
        expected_signal_date="20260925",
        expected_eligibility_source_date="20260924",
    )
    assert len(result.rows) == 100

    late_manifest = {
        **security_master_manifest,
        "captured_at": "2026-09-28T02:50:33+08:00",
    }
    monkeypatch.setattr(
        hk_0_2,
        "_load_verified_security_master",
        lambda _root, trade_date: (
            {f"HK.{index:05d}": {} for index in range(1, 101)},
            late_manifest,
        ),
    )
    with pytest.raises(hk_0_2.StoreError, match="capture date"):
        hk_0_2.read_verified_hk_0_2_pool(
            tmp_path,
            target_date="20260928",
            expected_signal_date="20260925",
            expected_eligibility_source_date="20260924",
        )


def test_split_date_capture_time_provenance_is_path_neutral_and_reversible(
    tmp_path: Path,
) -> None:
    from upstreams.v3_shared_data.shared_data.hk_0_2 import (
        HK_0_2_ROLE,
        HK_0_2_STAGE_ID,
        _decode_capture_at_provenance,
        _encode_capture_at_provenance,
    )
    from upstreams.v3_shared_data.shared_data.allowlist import SourceSpec

    captured_at = "2026-09-30T17:20:08+08:00"
    encoded = _encode_capture_at_provenance(captured_at)
    assert _decode_capture_at_provenance(encoded) == captured_at
    assert not any(character in encoded for character in (":", "/", "\\"))

    source_path = tmp_path / "pool.csv"
    source_path.write_text("rank\n1\n", encoding="utf-8")
    source = SourceSpec(
        source_id="hkconnect_0_2_frozen_prob_active",
        role=HK_0_2_ROLE,
        trade_date="20261006",
        market="HK_CONNECT",
        stages=(HK_0_2_STAGE_ID,),
        cutoff_at="17:30:00",
        source_path=source_path,
        provenance={"security_master_captured_at": encoded},
    )
    source.validate()

    legacy = SourceSpec(
        **{
            **source.__dict__,
            "provenance": {"security_master_captured_at": captured_at},
        }
    )
    with pytest.raises(ValueError, match="path-neutral"):
        legacy.validate()
