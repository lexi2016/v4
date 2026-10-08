"""Synthetic contract regressions for the 20261008 HK Stage failure.

These fixtures reproduce the reported date/field shape, not the missing real
business rows or their SHA. No fixture is evidence of production recovery.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from infrastructure.preselection_pool_store import PreselectionPoolStore
from stage_center import runner
from test_hk_prior_observation_source_binding import (
    _hk_d1_pool,
    _rewrite_pool_trio,
    _split_date_d1_pool,
    _write_released_materializer_lock,
)


TARGET = "20261008"
PRICE_DATE = "20261007"
ELIGIBILITY_DATE = "20260930"
POOL = "hkconnect_d1_top100"


def _valid_split_pool() -> dict:
    payload = _split_date_d1_pool(TARGET, PRICE_DATE, ELIGIBILITY_DATE)
    # Current canonical requires this existing v1 field. The frozen historical
    # fixture omits it; keep the original tests unmodified and complete only
    # this new synthetic fixture.
    payload["historical_provenance"]["d1_source_artifact_relative"] = payload["source_path"]
    return payload


def _install(tmp_path: Path, payload: dict, secondary: bool = True):
    primary = tmp_path / "v4-primary"
    source = tmp_path / "v35-source" if secondary else primary
    primary.mkdir()
    store = PreselectionPoolStore(source)
    store.materialize(payload)
    if secondary:
        _write_released_materializer_lock(source)
    return primary, source, store


def _binding(primary: Path, source: Path, secondary: bool = True):
    return runner._build_hk_stage_binding(
        primary, TARGET, preselection_source_root=source if secondary else None
    )


def test_reported_shape_missing_provenance_is_a_failure_not_zero_selection(tmp_path):
    payload = _hk_d1_pool(TARGET, ELIGIBILITY_DATE)
    for field in ("signal_date", "target_date", "stage_selection_eligible"):
        payload.pop(field)
    payload["source_run_id"] = "synthetic-observed-shape-not-live-run"
    primary, source, store = _install(tmp_path, payload)
    before = store.read_pool_snapshot(TARGET, POOL)

    with pytest.raises(runner.RunnerError, match="split-date eligibility provenance missing"):
        _binding(primary, source)

    after = store.read_pool_snapshot(TARGET, POOL)
    assert after == before
    assert {row["signal_date"] for row in after["artifact"]["rows"]} == {ELIGIBILITY_DATE}
    assert "historical_provenance" not in after["artifact"]


def test_complete_provenance_does_not_relabel_stale_price_rows(tmp_path):
    payload = _valid_split_pool()
    for row in payload["rows"]:
        row["signal_date"] = ELIGIBILITY_DATE
    primary, source, store = _install(tmp_path, payload)
    before = store.read_pool_snapshot(TARGET, POOL)

    with pytest.raises(runner.RunnerError, match="row market/signal_date mismatch"):
        _binding(primary, source)

    assert store.read_pool_snapshot(TARGET, POOL) == before


@pytest.mark.parametrize("missing", ["source_manifest_sha256", "source_receipt_sha256"])
def test_physical_trio_cannot_supply_missing_upstream_identity(tmp_path, missing):
    payload = _valid_split_pool()
    primary, source, store = _install(tmp_path, payload)
    snapshot = store.read_pool_snapshot(TARGET, POOL)
    payload.pop(missing)
    provenance_field = "d1_" + missing
    physical_field = "manifest_raw_sha256" if "manifest" in missing else "receipt_raw_sha256"
    payload["historical_provenance"][provenance_field] = snapshot[physical_field]
    _rewrite_pool_trio(store, TARGET, POOL, payload)
    before = {p: p.read_bytes() for p in (source / snapshot[key] for key in (
        "artifact_relative", "manifest_relative", "receipt_relative"
    ))}

    with pytest.raises(runner.RunnerError, match="binding mismatch|provenance identity mismatch"):
        _binding(primary, source)

    assert all(path.read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize("captured_at", [
    "2026-10-01T00:00:00+08:00",
    "2026-09-30T17:20:08",
    "",
])
def test_capture_time_must_be_existing_valid_eligibility_day_evidence(tmp_path, captured_at):
    payload = _valid_split_pool()
    primary, source, store = _install(tmp_path, payload)
    payload["historical_provenance"]["eligibility_source_captured_at"] = captured_at
    _rewrite_pool_trio(store, TARGET, POOL, payload)

    with pytest.raises(runner.RunnerError, match="capture|captured"):
        _binding(primary, source)


@pytest.mark.parametrize("secondary", [False, True])
@pytest.mark.parametrize("changed_part", ["manifest", "receipt"])
def test_validation_rechecks_whole_physical_trio_at_return(tmp_path, monkeypatch, secondary, changed_part):
    payload = _valid_split_pool()
    primary, source, store = _install(tmp_path, payload, secondary)
    snapshot = store.read_pool_snapshot(TARGET, POOL)
    artifact_path = source / snapshot["artifact_relative"]
    changed_path = source / snapshot[f"{changed_part}_relative"]
    original_sha = runner._sha
    changed = False

    def change_other_trio_member_after_artifact_hash(path):
        nonlocal changed
        digest = original_sha(path)
        if Path(path) == artifact_path and not changed:
            changed = True
            document = json.loads(changed_path.read_text())
            if changed_part == "manifest":
                # Simulate an independently published pool altering the shared
                # date manifest while leaving the HK artifact bytes intact.
                document["a_d1_premarket_pool"] = hashlib.sha256(b"synthetic concurrent pool").hexdigest()
            else:
                document["source_run_id"] = "synthetic-concurrent-receipt"
            changed_path.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return digest

    monkeypatch.setattr(runner, "_sha", change_other_trio_member_after_artifact_hash)
    with pytest.raises(runner.RunnerError, match="snapshot|trio|identity changed"):
        runner._validate_hk_d1(
            primary, TARGET, preselection_source_root=source if secondary else None
        )
    assert changed


@pytest.mark.parametrize("secondary", [False, True])
def test_valid_split_date_binding_preserves_source_identity_without_substitution(tmp_path, secondary):
    payload = _valid_split_pool()
    primary, source, store = _install(tmp_path, payload, secondary)
    snapshot = store.read_pool_snapshot(TARGET, POOL)

    binding = _binding(primary, source, secondary)

    assert binding.status == "READY"
    assert binding.role == "HK_CONNECT_D1_TOP100"
    assert binding.trade_date == TARGET
    assert len(binding.codes) == len(set(binding.codes)) == 100
    assert binding.sha256 == snapshot["artifact_raw_sha256"]
    assert "hk_d1_membership=exact_date_top100" in binding.evidence
    assert f"hk_d1_json={source / snapshot['artifact_relative']}" in binding.evidence
    assert payload["source_sha256"] != snapshot["artifact_raw_sha256"]
    assert payload["source_manifest_sha256"] != snapshot["manifest_raw_sha256"]
    assert payload["source_receipt_sha256"] != snapshot["receipt_raw_sha256"]
    assert snapshot["artifact"]["historical_provenance"] == payload["historical_provenance"]
    assert runner._validated_hk_binding_evidence(binding, TARGET)
    assert store.read_pool_snapshot(TARGET, POOL) == snapshot
