from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from infrastructure.owned_io import SafeRoot
from infrastructure.preselection_pool_store import PreselectionPoolStore
from stage_center.calendar import TradingDayState, resolve_market_states
from stage_center.runner import RunnerError, _build_hk_d1_binding, _build_hk_stage_binding


SAFETY_FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _hk_d1_pool(trade_date: str, signal_date: str) -> dict[str, object]:
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": trade_date,
        "target_date": trade_date,
        "signal_date": signal_date,
        "pool_id": "hkconnect_d1_top100",
        "display_name": "synthetic verified HK D-1",
        "market": "HK",
        "status": "STRICT_0_2_READY",
        "producer_id": "v3_shared_hk_0_2_consumer_v1",
        "source_role": "SHARED_VERIFIED_HK_0_2",
        "source_path": "synthetic/verified-pool.json",
        "source_sha256": hashlib.sha256(f"pool:{trade_date}".encode()).hexdigest(),
        "stage_selection_eligible": True,
        "rows": [
            {
                "symbol": f"HK.{rank:05d}",
                "code": f"HK.{rank:05d}",
                "market": "HK",
                "pool_id": "hkconnect_d1_top100",
                "signal_date": signal_date,
                "trade_date": trade_date,
                "target_date": trade_date,
                "available_at": f"{signal_date}T15:00:00+08:00",
                "selected_strategy": "prob_active",
                "prob_active": 0.5,
                **SAFETY_FLAGS,
            }
            for rank in range(1, 101)
        ],
        "cannot_confirm": [],
        **SAFETY_FLAGS,
    }


def _write_released_materializer_lock(root: Path) -> None:
    lock = root / "preselection_pools" / ".materialize.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        '{"schema_version":"v3_5_interprocess_lock.v1","pid":2147483647,"token":"RELEASED"}',
        encoding="utf-8",
    )
    lock.chmod(0o600)


def _rewrite_pool_trio(
    store: PreselectionPoolStore,
    trade_date: str,
    pool_id: str,
    artifact: dict[str, object],
) -> None:
    artifact_relative, receipt_relative = store._relative(trade_date, pool_id)
    manifest_relative = f"preselection_pools/{trade_date}/manifest.json"
    artifact_bytes = json.dumps(
        artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.sha256(artifact_bytes).hexdigest()
    manifest = store._read(manifest_relative)
    manifest[pool_id] = digest
    store._write(artifact_relative, artifact)
    store._write(manifest_relative, manifest)
    store._write(
        receipt_relative,
        store._receipt(
            trade_date=trade_date,
            pool_id=pool_id,
            artifact_path=artifact_relative,
            artifact_sha256=digest,
            payload=artifact,
        ),
    )


def _observe_prior_pool(
    primary_root: Path,
    source_root: Path,
    *,
    trade_date: str = "20260925",
):
    return _build_hk_stage_binding(
        primary_root,
        trade_date,
        preselection_source_root=source_root,
    )


def _split_date_d1_pool(
    trade_date: str,
    signal_date: str,
    eligibility_source_date: str,
) -> dict[str, object]:
    payload = _hk_d1_pool(trade_date, signal_date)
    source_run_id = f"synthetic-hk-d1-{trade_date}-{signal_date}"
    source_sha256 = hashlib.sha256(f"source:{trade_date}".encode()).hexdigest()
    source_manifest_sha256 = hashlib.sha256(
        f"manifest:{trade_date}".encode()
    ).hexdigest()
    source_receipt_sha256 = hashlib.sha256(
        f"receipt:{trade_date}".encode()
    ).hexdigest()
    payload.update(
        {
            "source_run_id": source_run_id,
            "source_sha256": source_sha256,
            "source_manifest_sha256": source_manifest_sha256,
            "source_receipt_sha256": source_receipt_sha256,
            "historical_provenance": {
                "schema_version": "v4.hk_d1_split_date_provenance.v1",
                "price_signal_date": signal_date,
                "eligibility_source_date": eligibility_source_date,
                "eligibility_source_run_id": f"eligibility-{eligibility_source_date}",
                "eligibility_source_artifact_sha256": "1" * 64,
                "d1_source_run_id": source_run_id,
                "d1_source_artifact_sha256": source_sha256,
                "d1_source_manifest_sha256": source_manifest_sha256,
                "d1_source_receipt_sha256": source_receipt_sha256,
                "eligibility_source_captured_at": (
                    f"{eligibility_source_date[:4]}-{eligibility_source_date[4:6]}-"
                    f"{eligibility_source_date[6:]}T17:20:08+08:00"
                ),
            },
        }
    )
    return payload


def test_real_calendar_prefers_verified_exact_target_pool_as_research_observation(
    tmp_path: Path,
) -> None:
    target_date = "20261007"
    target_signal_date = "20261006"
    eligibility_source_date = "20260930"
    states = resolve_market_states(target_date)
    assert states["hk_securities"] is TradingDayState.FULL_TRADING_DAY
    assert states["hk_connect"] is TradingDayState.NON_TRADING_DAY

    primary = tmp_path / "v4-primary"
    source = tmp_path / "v35-source"
    primary.mkdir()
    store = PreselectionPoolStore(source)
    prior_payload = _hk_d1_pool(eligibility_source_date, "20260929")
    target_codes = tuple(f"HK.{20_000 + rank:05d}" for rank in range(1, 101))
    target_payload = _split_date_d1_pool(
        target_date, target_signal_date, eligibility_source_date
    )
    target_payload["rows"] = [
        {
            **row,
            "code": code,
            "symbol": code,
            "market": "HK",
            "pool_id": "hkconnect_d1_top100",
            "target_date": target_date,
            "trade_date": target_date,
            "signal_date": target_signal_date,
        }
        for row, code in zip(target_payload["rows"], target_codes, strict=True)
    ]
    store.materialize(prior_payload)
    store.materialize(target_payload)
    _write_released_materializer_lock(source)
    target_snapshot = store.read_pool_snapshot(target_date, "hkconnect_d1_top100")

    binding = _build_hk_stage_binding(
        primary,
        target_date,
        preselection_source_root=source,
    )

    assert binding.role == "HK_CONNECT_D1_TOP100"
    assert binding.sha256 == target_snapshot["artifact_raw_sha256"]
    assert set(binding.codes) == set(target_codes)
    assert "hk_d1_binding_mode=EXACT_TARGET_DATE_RESEARCH_OBSERVATION" in binding.evidence
    assert "hk_d1_source_trade_date=20261007" in binding.evidence
    assert "hk_d1_source_signal_date=20261006" in binding.evidence
    assert "hk_observation_mode=HK_SECURITIES_OPEN_HK_CONNECT_CLOSED" in binding.evidence
    assert "hk_observation_scope=RESEARCH_ONLY" in binding.evidence
    assert "hk_observation_capture_time=CANNOT_CONFIRM" in binding.evidence
    assert "hk_observation_pit_status=CANNOT_CONFIRM" in binding.evidence
    assert all(f"{flag}=false" in binding.evidence for flag in SAFETY_FLAGS)


def test_missing_exact_target_pool_keeps_prior_connect_observation_fallback(
    tmp_path: Path,
) -> None:
    target_date = "20261007"
    eligibility_source_date = "20260930"
    states = resolve_market_states(target_date)
    assert states["hk_securities"] is TradingDayState.FULL_TRADING_DAY
    assert states["hk_connect"] is TradingDayState.NON_TRADING_DAY

    primary = tmp_path / "v4-primary"
    source = tmp_path / "v35-source"
    primary.mkdir()
    store = PreselectionPoolStore(source)
    prior = _hk_d1_pool(eligibility_source_date, "20260929")
    store.materialize(prior)
    _write_released_materializer_lock(source)
    prior_snapshot = store.read_pool_snapshot(
        eligibility_source_date, "hkconnect_d1_top100"
    )

    binding = _build_hk_stage_binding(
        primary,
        target_date,
        preselection_source_root=source,
    )

    assert binding.role == "HK_CONNECT_D1_TOP100_PRIOR_VERIFIED_OBSERVATION"
    assert binding.sha256 == prior_snapshot["artifact_raw_sha256"]
    assert f"hk_d1_source_trade_date={eligibility_source_date}" in binding.evidence
    assert "hk_d1_binding_mode=PRIOR_CONNECT_DATE_FALLBACK" in binding.evidence
    assert "hk_d1_exact_target_status=CANNOT_CONFIRM" in binding.evidence


def test_target_pool_committed_after_absence_probe_cannot_return_prior_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_date = "20261007"
    eligibility_source_date = "20260930"
    primary = tmp_path / "v4-primary"
    source = tmp_path / "v35-source"
    primary.mkdir()
    prior_store = PreselectionPoolStore(source)
    prior_store.materialize(_hk_d1_pool(eligibility_source_date, "20260929"))
    _write_released_materializer_lock(source)
    target_store = PreselectionPoolStore(primary)
    target_payload = _hk_d1_pool(target_date, "20261006")

    original_read_bytes = SafeRoot.read_bytes
    committed = False
    manifest_relative = f"preselection_pools/{target_date}/manifest.json"

    def commit_after_missing_manifest(self, relative: str, *args, **kwargs):
        nonlocal committed
        try:
            return original_read_bytes(self, relative, *args, **kwargs)
        except FileNotFoundError:
            if (
                not committed
                and self.root == primary
                and relative == manifest_relative
            ):
                committed = True
                target_store.materialize(target_payload)
            raise

    monkeypatch.setattr(SafeRoot, "read_bytes", commit_after_missing_manifest)

    with pytest.raises(RunnerError, match="target pool appeared during prior fallback"):
        _build_hk_stage_binding(
            primary,
            target_date,
            preselection_source_root=source,
        )

    assert committed is True
    assert target_store.read_pool_snapshot(
        target_date, "hkconnect_d1_top100"
    )["artifact"]["trade_date"] == target_date


def test_corrupt_existing_exact_target_receipt_fails_closed_without_prior_fallback(
    tmp_path: Path,
) -> None:
    target_date = "20261007"
    eligibility_source_date = "20260930"
    primary = tmp_path / "v4-primary"
    source = tmp_path / "v35-source"
    primary.mkdir()
    store = PreselectionPoolStore(source)
    store.materialize(_hk_d1_pool(eligibility_source_date, "20260929"))
    store.materialize(_hk_d1_pool(target_date, "20261006"))
    _write_released_materializer_lock(source)

    _, receipt_relative = store._relative(target_date, "hkconnect_d1_top100")
    receipt_path = source / receipt_relative
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["artifact_sha256"] = "0" * 64
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(RunnerError, match="exact target.*CANNOT_CONFIRM"):
        _build_hk_stage_binding(
            primary,
            target_date,
            preselection_source_root=source,
        )


def test_pending_exact_target_pool_commit_fails_closed_without_prior_fallback(
    tmp_path: Path,
) -> None:
    target_date = "20261007"
    eligibility_source_date = "20260930"
    primary = tmp_path / "v4-primary"
    source = tmp_path / "v35-source"
    primary.mkdir()
    store = PreselectionPoolStore(source)
    store.materialize(_hk_d1_pool(eligibility_source_date, "20260929"))
    store.materialize(_hk_d1_pool(target_date, "20261006"))
    _write_released_materializer_lock(source)
    pending = (
        source
        / "preselection_pending_commits"
        / target_date
        / "hkconnect_d1_top100.json"
    )
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text("{}", encoding="utf-8")

    with pytest.raises(RunnerError, match="exact target.*CANNOT_CONFIRM"):
        _build_hk_stage_binding(
            primary,
            target_date,
            preselection_source_root=source,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (("target_date", "20261006"), ("market", "A")),
)
def test_wrong_identity_on_existing_exact_target_pool_fails_closed(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    target_date = "20261007"
    primary = tmp_path / "v4-primary"
    source = tmp_path / "v35-source"
    primary.mkdir()
    store = PreselectionPoolStore(source)
    store.materialize(_hk_d1_pool("20260930", "20260929"))
    target = _hk_d1_pool(target_date, "20261006")
    store.materialize(target)
    target[field] = value
    _rewrite_pool_trio(store, target_date, "hkconnect_d1_top100", target)
    _write_released_materializer_lock(source)

    with pytest.raises(RunnerError, match="exact target.*CANNOT_CONFIRM"):
        _build_hk_stage_binding(
            primary,
            target_date,
            preselection_source_root=source,
        )


def test_hk_only_observation_binds_exact_previous_connect_trio_from_secondary_root(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "v4-primary"
    secondary = tmp_path / "v35-source"
    primary.mkdir()
    source_store = PreselectionPoolStore(secondary)
    source_store.materialize(_hk_d1_pool("20260924", "20260923"))
    _write_released_materializer_lock(secondary)
    snapshot = source_store.read_pool_snapshot("20260924", "hkconnect_d1_top100")

    binding = _observe_prior_pool(primary, secondary)

    assert binding.trade_date == "20260925"
    assert binding.role == "HK_CONNECT_D1_TOP100_PRIOR_VERIFIED_OBSERVATION"
    assert binding.sha256 == snapshot["artifact_raw_sha256"]
    assert len(binding.codes) == 100
    assert f"hk_d1_source_trade_date=20260924" in binding.evidence
    assert f"hk_d1_source_signal_date=20260923" in binding.evidence
    assert f"hk_d1_source_manifest_sha256={snapshot['manifest_raw_sha256']}" in binding.evidence
    assert f"hk_d1_source_receipt_sha256={snapshot['receipt_raw_sha256']}" in binding.evidence
    assert f"hk_observation_trade_date=20260925" in binding.evidence
    assert "hk_observation_mode=HK_SECURITIES_OPEN_HK_CONNECT_CLOSED" in binding.evidence
    assert "hk_observation_price_signal_date=20260924" in binding.evidence
    assert f"hk_d1_json={secondary / snapshot['artifact_relative']}" in binding.evidence
    after = source_store.read_pool_snapshot("20260924", "hkconnect_d1_top100")
    assert after["artifact"] == snapshot["artifact"]
    assert after["artifact"]["trade_date"] == "20260924"
    assert after["artifact"]["target_date"] == "20260924"
    assert {row["signal_date"] for row in after["artifact"]["rows"]} == {"20260923"}
    assert {row["available_at"] for row in after["artifact"]["rows"]} == {
        "20260923T15:00:00+08:00"
    }
    assert all(after["artifact"][flag] is False for flag in SAFETY_FLAGS)


def test_connect_open_target_requires_its_exact_date_even_when_older_pool_exists(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "v4-primary"
    secondary = tmp_path / "v35-source"
    primary.mkdir()
    PreselectionPoolStore(secondary).materialize(_hk_d1_pool("20260923", "20260922"))
    _write_released_materializer_lock(secondary)

    with pytest.raises(RunnerError, match="CANNOT_CONFIRM|exact-date|snapshot integrity"):
        _observe_prior_pool(primary, secondary, trade_date="20260924")


def test_missing_exact_previous_connect_session_never_falls_back_to_older_pool(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "v4-primary"
    secondary = tmp_path / "v35-source"
    primary.mkdir()
    PreselectionPoolStore(secondary).materialize(_hk_d1_pool("20260923", "20260922"))
    _write_released_materializer_lock(secondary)

    with pytest.raises(RunnerError, match="CANNOT_CONFIRM|snapshot integrity|exact-date"):
        _observe_prior_pool(primary, secondary)


def test_calendar_prior_connect_session_wins_over_a_newer_non_connect_pool_date(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "v4-primary"
    secondary = tmp_path / "v35-source"
    primary.mkdir()
    store = PreselectionPoolStore(secondary)
    store.materialize(_hk_d1_pool("20260213", "20260212"))
    store.materialize(_hk_d1_pool("20260220", "20260216"))
    _write_released_materializer_lock(secondary)
    expected = store.read_pool_snapshot("20260213", "hkconnect_d1_top100")

    binding = _observe_prior_pool(
        primary,
        secondary,
        trade_date="20260223",
    )

    assert binding.role == "HK_CONNECT_D1_TOP100_PRIOR_VERIFIED_OBSERVATION"
    assert binding.sha256 == expected["artifact_raw_sha256"]
    assert "hk_d1_source_trade_date=20260213" in binding.evidence
    assert "hk_d1_source_signal_date=20260212" in binding.evidence
    assert "hk_observation_price_signal_date=20260220" in binding.evidence


def test_incomplete_primary_owner_suppresses_valid_secondary_date_fallback(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "v4-primary"
    secondary = tmp_path / "v35-source"
    (primary / "preselection_pools" / "20260924").mkdir(parents=True)
    PreselectionPoolStore(secondary).materialize(
        _hk_d1_pool("20260924", "20260923")
    )
    _write_released_materializer_lock(secondary)

    with pytest.raises(RunnerError, match="CANNOT_CONFIRM|snapshot integrity"):
        _observe_prior_pool(primary, secondary)


@pytest.mark.parametrize("receipt_state", ["missing", "tampered"])
def test_prior_observation_rejects_missing_or_tampered_receipt(
    receipt_state: str,
    tmp_path: Path,
) -> None:
    primary = tmp_path / "v4-primary"
    secondary = tmp_path / "v35-source"
    primary.mkdir()
    store = PreselectionPoolStore(secondary)
    store.materialize(_hk_d1_pool("20260924", "20260923"))
    _write_released_materializer_lock(secondary)
    snapshot = store.read_pool_snapshot("20260924", "hkconnect_d1_top100")
    receipt = secondary / snapshot["receipt_relative"]
    if receipt_state == "missing":
        receipt.unlink()
    else:
        receipt.write_text('{"tampered":true}\n', encoding="utf-8")

    with pytest.raises(RunnerError, match="CANNOT_CONFIRM|integrity|receipt|snapshot"):
        _observe_prior_pool(primary, secondary)


@pytest.mark.parametrize("bad_signal_date", ["20260922", "20260925"])
def test_prior_observation_rejects_source_signal_date_that_fails_pit_calendar(
    bad_signal_date: str,
    tmp_path: Path,
) -> None:
    primary = tmp_path / "v4-primary"
    secondary = tmp_path / "v35-source"
    primary.mkdir()
    PreselectionPoolStore(secondary).materialize(_hk_d1_pool("20260924", bad_signal_date))
    _write_released_materializer_lock(secondary)

    with pytest.raises(RunnerError, match="signal_date mismatch|calendar CANNOT_CONFIRM"):
        _observe_prior_pool(primary, secondary)


def test_split_price_and_eligibility_dates_require_existing_historical_provenance(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "v4-primary"
    secondary = tmp_path / "v35-source"
    primary.mkdir()
    PreselectionPoolStore(secondary).materialize(
        _hk_d1_pool("20260506", "20260505")
    )
    _write_released_materializer_lock(secondary)

    with pytest.raises(RunnerError, match="split-date eligibility provenance missing"):
        _build_hk_d1_binding(
            primary,
            "20260506",
            preselection_source_root=secondary,
        )


def test_split_date_provenance_captured_after_eligibility_date_is_rejected(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "v4-primary"
    secondary = tmp_path / "v35-source"
    primary.mkdir()
    payload = _hk_d1_pool("20260506", "20260505")
    payload.update(
        {
            "source_run_id": "d1-source-run",
            "source_manifest_sha256": "a" * 64,
            "source_receipt_sha256": "b" * 64,
            "historical_provenance": {
                "schema_version": "v4.hk_d1_split_date_provenance.v1",
                "price_signal_date": "20260505",
                "eligibility_source_date": "20260430",
                "eligibility_source_run_id": "eligibility-run",
                "eligibility_source_captured_at": "2026-05-01T09:30:00+08:00",
                "eligibility_source_artifact_sha256": "c" * 64,
                "d1_source_run_id": "d1-source-run",
                "d1_source_artifact_sha256": payload["source_sha256"],
                "d1_source_manifest_sha256": "a" * 64,
                "d1_source_receipt_sha256": "b" * 64,
            },
        }
    )
    PreselectionPoolStore(secondary).materialize(payload)
    _write_released_materializer_lock(secondary)

    with pytest.raises(RunnerError, match="eligibility source capture date mismatch"):
        _build_hk_d1_binding(
            primary,
            "20260506",
            preselection_source_root=secondary,
        )


def test_hk_securities_closed_date_does_not_bind_an_observation(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "v4-primary"
    secondary = tmp_path / "v35-source"
    primary.mkdir()
    PreselectionPoolStore(secondary).materialize(
        _hk_d1_pool("20260930", "20260929")
    )
    _write_released_materializer_lock(secondary)

    with pytest.raises(RunnerError, match="closed|CANNOT_CONFIRM|unavailable"):
        _observe_prior_pool(primary, secondary, trade_date="20261001")
