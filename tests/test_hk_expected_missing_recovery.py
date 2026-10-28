from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from infrastructure.data_store import NativeDataStore
from infrastructure.preselection_pool_store import (
    HK_EXPECTED_MISSING_SOURCE_SHA256,
    HK_EXPECTED_MISSING_SUCCESSOR_SHA256,
    PreselectionPoolStore,
)
from ops.materialize_scheduled_preselection import main


RECOVERY_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/v4_hk_history_r5_acceptance_20261002"
)
BOUND = json.loads((RECOVERY_ROOT / "api_integration/ACTIVE_BINDINGS.json").read_text())
SOURCE_ROOT = Path(BOUND["environment_bindings"]["V35_PRESELECTION_SOURCE_ROOT"])
SHARED_DATA_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data"
)
ELIGIBILITY_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data"
)
SHARED_PACKAGE_ROOT = RECOVERY_ROOT / "local_fix/roots/shared_package"
DATE = "20260930"
OLD_ARTIFACT_SHA256 = "972643a7a0ccc91d64681f5a62ac0cb8bd8940c2e3fc7b0a1ebc4370f29288df"
OLD_RECEIPT_SHA256 = "61f19f90c8786511e685b8698351e25ba500f1c8979cb6e1a060706f5128ca2b"
TOP100_SHA256 = "8a548960a26268ec248d680466153acad0cfc1764b565d6cee06e9392590b666"


def _safe_temp_root() -> Path:
    base = Path(__file__).resolve().parents[1] / ".test_hk_recovery_roots"
    base.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="recovery-", dir=base))


def _seed_exact_source_day(root: Path) -> dict[str, bytes]:
    source_day = SOURCE_ROOT / "preselection_pools" / DATE
    target_day = root / "preselection_pools" / DATE
    shutil.copytree(source_day, target_day)
    placeholder = target_day / "hkconnect_d1_top100.json"
    receipt = target_day / "receipts/hkconnect_d1_top100.json"
    # The original owner flow has since replaced the live placeholder. Seed
    # the isolated test root from its archived, SHA-pinned preimage instead.
    revision_root = SOURCE_ROOT / "preselection_revisions" / DATE / "hkconnect_d1_top100"
    placeholder_bytes = (revision_root / f"{OLD_ARTIFACT_SHA256}.json").read_bytes()
    revision_receipt = json.loads(
        (revision_root / f"{OLD_ARTIFACT_SHA256}.receipt.json").read_text()
    )
    receipt_bytes = json.dumps(
        revision_receipt["main_receipt"], sort_keys=True, separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    assert hashlib.sha256(placeholder_bytes).hexdigest() == OLD_ARTIFACT_SHA256
    assert hashlib.sha256(receipt_bytes).hexdigest() == OLD_RECEIPT_SHA256
    placeholder.write_bytes(placeholder_bytes)
    receipt.write_bytes(receipt_bytes)
    manifest_path = target_day / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["hkconnect_d1_top100"] = OLD_ARTIFACT_SHA256
    manifest_path.write_bytes(json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8"))
    # The actual source bytes are copied to an isolated store; A files must
    # remain byte-identical across the HK-only recovery transaction.
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in target_day.iterdir()
        if path.is_file() and path.name not in {"manifest.json"}
        and path.name.startswith(("a_", "a_share_", "wechat_"))
    } | {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in (target_day / "receipts").iterdir()
        if path.is_file() and path.name.startswith(("a_", "a_share_", "wechat_"))
    }


def _recovery_args(root: Path) -> list[str]:
    return [
        "--recover-hk-expected-missing",
        "--trade-date", DATE,
        "--signal-date", "20260929",
        "--eligibility-source-date", "20260929",
        "--data-root", str(root),
        "--shared-data-root", str(SHARED_DATA_ROOT),
        "--eligibility-universe-root", str(ELIGIBILITY_ROOT),
        "--shared-package-root", str(SHARED_PACKAGE_ROOT),
        "--expected-old-artifact-sha256", OLD_ARTIFACT_SHA256,
        "--expected-old-receipt-sha256", OLD_RECEIPT_SHA256,
        "--expected-source-sha256", HK_EXPECTED_MISSING_SOURCE_SHA256,
        "--expected-successor-sha256", HK_EXPECTED_MISSING_SUCCESSOR_SHA256,
    ]


def _install_catalog(root: Path) -> None:
    NativeDataStore(root).import_catalog({
        "schema_version": "v3_trade_calendar.v1",
        "system_date": DATE,
        "stage_dates": [DATE],
        "future_target_dates": [],
        "materialized_rows": {DATE: 205},
    })


def test_hk_only_owner_cli_api_projection_and_rollback_chain(capsys) -> None:
    root = _safe_temp_root()
    try:
        a_bytes_before = _seed_exact_source_day(root)
        _install_catalog(root)

        assert main(_recovery_args(root)) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == "STRICT_0_2_READY"
        assert result["row_count"] == 100
        assert result["artifact_sha256"] == "f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901"
        assert result["previous_sha256"] == OLD_ARTIFACT_SHA256
        assert result["receipt_raw_sha256"]
        assert result["production_allowed"] is False
        assert result["buy_gate_updated"] is False
        assert result["orders_sent"] is False

        store = PreselectionPoolStore(root)
        snapshot = store.read_pool_snapshot(DATE, "hkconnect_d1_top100")
        artifact = snapshot["artifact"]
        assert artifact["source_sha256"] == TOP100_SHA256
        assert artifact["target_date"] == DATE
        assert artifact["signal_date"] == "20260929"
        assert artifact["historical_provenance"]["eligibility_source_date"] == "20260929"
        assert len(artifact["rows"]) == 100
        assert json.loads((root / result["recovery_record"]).read_text())["replacement_sha256"] == result["artifact_sha256"]

        client = TestClient(create_app(
            data_root=root,
            preselection_source_root=root,
            current_date=DATE,
            stage_center_selection_root=root / "stage",
        ))
        response = client.get("/api/v3/preselection-pools", params={"date": DATE, "limit": 300})
        assert response.status_code == 200
        body = response.json()
        assert body["market_totals"] == {"A": 205, "HK": 100}
        hk_pool = next(pool for pool in body["pools"] if pool["pool_id"] == "hkconnect_d1_top100")
        assert hk_pool["pool_size"] == 100
        assert hk_pool["source_role"] == "SHARED_VERIFIED_HK_0_2"

        for relative, expected in a_bytes_before.items():
            assert (root / relative).read_bytes() == expected
        manifest = json.loads((root / f"preselection_pools/{DATE}/manifest.json").read_text())
        source_manifest = json.loads((SOURCE_ROOT / f"preselection_pools/{DATE}/manifest.json").read_text())
        for pool_id, source_sha in source_manifest.items():
            if pool_id.startswith(("a_", "a_share_", "wechat_")):
                assert manifest[pool_id] == source_sha

        assert main([
            "--rollback-hk-expected-missing",
            "--data-root", str(root),
            "--expected-replacement-sha256", result["artifact_sha256"],
        ]) == 0
        rollback = json.loads(capsys.readouterr().out)
        assert rollback["sha256"] == OLD_ARTIFACT_SHA256
        rollback_record = json.loads((root / rollback["rollback_record"]).read_text())
        assert rollback_record["previous_recovery_sha256"] == result["artifact_sha256"]
        assert rollback_record["restored_sha256"] == OLD_ARTIFACT_SHA256
        assert rollback_record["record_status"] == "ROLLED_BACK"
        for relative, expected in a_bytes_before.items():
            assert (root / relative).read_bytes() == expected
    finally:
        shutil.rmtree(root)


@pytest.mark.parametrize("mutation,expected_error", [
    ("source", "verified source SHA mismatch"),
    ("successor", "expected successor artifact SHA mismatch"),
])
def test_hk_recovery_rejects_unpinned_replacement_before_any_store_write(
    mutation: str, expected_error: str,
) -> None:
    root = _safe_temp_root()
    try:
        _seed_exact_source_day(root)
        _install_catalog(root)
        store = PreselectionPoolStore(root)
        from domains.preselection_materializer import build_shared_hk_0_2_pool

        artifact = build_shared_hk_0_2_pool(
            SHARED_DATA_ROOT,
            trade_date=DATE,
            signal_date="20260929",
            eligibility_source_date="20260929",
            eligibility_universe_root=ELIGIBILITY_ROOT,
            shared_package_root=SHARED_PACKAGE_ROOT,
        )
        if mutation == "source":
            artifact["source_sha256"] = "0" * 64
            artifact["historical_provenance"]["d1_source_artifact_sha256"] = "0" * 64
        else:
            artifact["rows"][0]["name"] = str(artifact["rows"][0].get("name") or "") + " altered"
        before = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()
        }
        with pytest.raises(ValueError, match=expected_error):
            store.recover_hk_expected_missing(
                artifact,
                expected_old_sha256=OLD_ARTIFACT_SHA256,
                expected_old_receipt_sha256=OLD_RECEIPT_SHA256,
                expected_source_sha256=HK_EXPECTED_MISSING_SOURCE_SHA256,
                expected_successor_sha256=HK_EXPECTED_MISSING_SUCCESSOR_SHA256,
            )
        after = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()
        }
        assert after == before
        assert not (root / "preselection_revisions").exists()
        assert not (root / "preselection_recoveries").exists()
    finally:
        shutil.rmtree(root)


@pytest.mark.parametrize("pin_flag", [
    "--expected-source-sha256", "--expected-successor-sha256",
])
def test_hk_owner_cli_rejects_wrong_pins_before_calling_reader(pin_flag: str) -> None:
    args = _recovery_args(Path("/tmp/hk-r5-invalid-pin-must-not-be-read"))
    args[args.index(pin_flag) + 1] = "0" * 64
    reader_called = False

    def forbidden_reader(*_args, **_kwargs):
        nonlocal reader_called
        reader_called = True
        raise AssertionError("reader must not run for mismatched fixed pins")

    with pytest.raises(SystemExit) as error:
        main(args, hk_pool_reader=forbidden_reader)
    assert error.value.code == 2
    assert reader_called is False


def test_hk_rollback_final_record_write_failure_is_retryable(
    capsys, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _safe_temp_root()
    try:
        _seed_exact_source_day(root)
        _install_catalog(root)
        assert main(_recovery_args(root)) == 0
        recovered = json.loads(capsys.readouterr().out)
        record_relative = (
            f"preselection_recoveries/{DATE}/hkconnect_d1_top100/"
            f"rollback-{recovered['artifact_sha256']}.json"
        )
        original_write = PreselectionPoolStore._write
        writes_to_record = 0

        def fail_final_record_once(self, relative, value):
            nonlocal writes_to_record
            if relative == record_relative:
                writes_to_record += 1
                if writes_to_record == 2:
                    raise OSError("injected final rollback record write failure")
            return original_write(self, relative, value)

        monkeypatch.setattr(PreselectionPoolStore, "_write", fail_final_record_once)
        assert main([
            "--rollback-hk-expected-missing",
            "--data-root", str(root),
            "--expected-replacement-sha256", recovered["artifact_sha256"],
        ]) == 1
        failed = json.loads(capsys.readouterr().out)
        assert "injected final rollback record write failure" in failed["error"]
        store = PreselectionPoolStore(root)
        snapshot = store.read_pool_snapshot(DATE, "hkconnect_d1_top100")
        assert snapshot["artifact_sha256"] == OLD_ARTIFACT_SHA256
        assert snapshot["receipt"] == store._receipt(
            trade_date=DATE,
            pool_id="hkconnect_d1_top100",
            artifact_path=snapshot["artifact_relative"],
            artifact_sha256=OLD_ARTIFACT_SHA256,
            payload=snapshot["artifact"],
        )
        pending = json.loads((root / record_relative).read_text())
        assert pending["record_status"] == "ROLLBACK_PENDING"

        monkeypatch.setattr(PreselectionPoolStore, "_write", original_write)
        assert main([
            "--rollback-hk-expected-missing",
            "--data-root", str(root),
            "--expected-replacement-sha256", recovered["artifact_sha256"],
        ]) == 0
        retried = json.loads(capsys.readouterr().out)
        assert retried["sha256"] == OLD_ARTIFACT_SHA256
        completed = json.loads((root / record_relative).read_text())
        assert completed["record_status"] == "ROLLED_BACK"

        # A completed retry remains an idempotent readback of the pinned old
        # trio and does not create a second recovery record.
        assert main([
            "--rollback-hk-expected-missing",
            "--data-root", str(root),
            "--expected-replacement-sha256", recovered["artifact_sha256"],
        ]) == 0
        idempotent = json.loads(capsys.readouterr().out)
        assert idempotent["sha256"] == OLD_ARTIFACT_SHA256
    finally:
        shutil.rmtree(root)


def test_hk_recovery_rejects_bad_compare_and_swap_and_ready_preimage() -> None:
    root = _safe_temp_root()
    try:
        _seed_exact_source_day(root)
        _install_catalog(root)
        store = PreselectionPoolStore(root)
        from domains.preselection_materializer import build_shared_hk_0_2_pool

        artifact = build_shared_hk_0_2_pool(
            SHARED_DATA_ROOT,
            trade_date=DATE,
            signal_date="20260929",
            eligibility_source_date="20260929",
            eligibility_universe_root=ELIGIBILITY_ROOT,
            shared_package_root=SHARED_PACKAGE_ROOT,
        )
        with pytest.raises(ValueError, match="pinned artifact and receipt CAS"):
            store.recover_hk_expected_missing(
                artifact,
                expected_old_sha256="0" * 64,
                expected_old_receipt_sha256=OLD_RECEIPT_SHA256,
                expected_source_sha256=HK_EXPECTED_MISSING_SOURCE_SHA256,
                expected_successor_sha256=HK_EXPECTED_MISSING_SUCCESSOR_SHA256,
            )
        with pytest.raises(ValueError, match="pinned artifact and receipt CAS"):
            store.recover_hk_expected_missing(
                artifact,
                expected_old_sha256=OLD_ARTIFACT_SHA256,
                expected_old_receipt_sha256="0" * 64,
                expected_source_sha256=HK_EXPECTED_MISSING_SOURCE_SHA256,
                expected_successor_sha256=HK_EXPECTED_MISSING_SUCCESSOR_SHA256,
            )
        store.recover_hk_expected_missing(
            artifact,
            expected_old_sha256=OLD_ARTIFACT_SHA256,
            expected_old_receipt_sha256=OLD_RECEIPT_SHA256,
            expected_source_sha256=HK_EXPECTED_MISSING_SOURCE_SHA256,
            expected_successor_sha256=HK_EXPECTED_MISSING_SUCCESSOR_SHA256,
        )
        with pytest.raises(ValueError, match="compare-and-swap preimage mismatch"):
            store.recover_hk_expected_missing(
                artifact,
                expected_old_sha256=OLD_ARTIFACT_SHA256,
                expected_old_receipt_sha256=OLD_RECEIPT_SHA256,
                expected_source_sha256=HK_EXPECTED_MISSING_SOURCE_SHA256,
                expected_successor_sha256=HK_EXPECTED_MISSING_SUCCESSOR_SHA256,
            )
    finally:
        shutil.rmtree(root)
