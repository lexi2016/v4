from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from stage_center import raw_store, runner
from stage_center.acquisition import SourceResult, StageUniverseBinding
from stage_center.live_collectors import production_selection_builders
from stage_center.selection import SelectionStore


TRADE_DATE = "20260930"
STAGE_ID = "STAGE_0930_0935"
POOL_SOURCE_DATE = "20260929"
POOL_SIGNAL_DATE = "20260929"
_DEFAULT_TOKEN = object()


def _fixture_case(tmp_path: Path):
    codes = tuple(f"HK.{10000 + index:05d}" for index in range(100))
    observed = tuple(sorted(codes[:75]))
    missing = tuple(sorted(codes[75:]))
    # The consumer binds the physical preselection object by target date;
    # the producer's source trade date remains in the immutable payload.
    pool_root = tmp_path / "preselection_pools" / TRADE_DATE
    pool_root.mkdir(parents=True)
    pool_path = pool_root / "hkconnect_d1_top100.json"
    pool_payload = {
        "schema_version": "test.legacy.preselection_pool.v1",
        "trade_date": POOL_SOURCE_DATE,
        "target_date": TRADE_DATE,
        "signal_date": POOL_SIGNAL_DATE,
        "market": "HK",
        "pool_id": "hkconnect_d1_top100",
        "source_run_id": "test-pool-run-20260929",
        "rows": [
            {
                "code": code,
                "market": "HK",
                "name": f"D1 name {code}",
                "candidate_lanes": [],
                "signal_date": POOL_SIGNAL_DATE,
                "target_date": TRADE_DATE,
            }
            for code in codes
        ],
        "status": "STRICT_0_2_READY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    pool_path.write_text(json.dumps(pool_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    pool_sha = hashlib.sha256(pool_path.read_bytes()).hexdigest()
    code_set_sha = raw_store.canonical_sha(sorted(codes))

    source_rows = tuple(
        {
            "batch_index": index,
            "code": code,
            "name": code,
            "update_time": f"2026-09-30 09:35:00",
            "last_price": 1.0 + index / 1000,
            "open_price": 1.0,
            "high_price": 1.1,
            "low_price": 0.9,
            "prev_close_price": 1.0,
            "turnover": 1000.0,
            "volume": 100.0,
            "bid_price": None,
            "ask_price": None,
            "bid_vol": None,
            "ask_vol": None,
            "window_start": "2026-09-30 09:31:00",
            "window_end": "2026-09-30 09:35:00",
            "bar_count": 5,
            "temporal_cutoff_safe": False,
            "candidate_lanes": [],
        }
        for index, code in enumerate(observed, start=1)
    )
    page_set_sha = "b" * 64
    required_evidence = sorted(
        {
            "historical_provider=pytdx_exhq",
            "historical_capture_after_target_cutoff=true",
            "historical_temporal_cutoff_safe=false",
            "historical_formal_stage_eligibility=CANNOT_CONFIRM",
            "historical_natural_time_capture=CANNOT_CONFIRM",
            "historical_pit_safe=false",
            "historical_price_signal_date=20260929",
            "historical_source_page_set_sha256=" + page_set_sha,
            "production_allowed=false",
            "buy_gate_updated=false",
            "orders_sent=false",
        }
    )
    cannot_confirm = raw_store._HISTORICAL_OBSERVATION_REQUIRED_CANNOT_CONFIRM
    manifest = {
        "schema_version": raw_store.HISTORICAL_OBSERVATION_MANIFEST_SCHEMA,
        "contract_id": raw_store.HISTORICAL_OBSERVATION_CONTRACT_ID,
        "target": {
            "trade_date": TRADE_DATE,
            "stage_id": STAGE_ID,
            "market": "HK_CONNECT",
            "source_id": "pytdx_exhq",
            "source_status": "PARTIAL_WITH_ROWS",
            "requested_rows": 100,
            "historical_backfill": True,
            "observation_mode": "AFTERFACT_RESEARCH_ONLY",
        },
        "pool": {
            "source_date": POOL_SOURCE_DATE,
            "signal_date": POOL_SIGNAL_DATE,
            "artifact_sha256": pool_sha,
            "source_run_id": "hk-d1-test-pool-run",
            "code_set_sha256": code_set_sha,
            "codes": sorted(codes),
        },
        "observation": {
            "source_page_set_sha256": page_set_sha,
            "price_signal_date": "20260929",
            "raw_artifact_sha256": raw_store._raw_artifact_csv_sha256(TRADE_DATE, source_rows),
            "observed_codes": list(observed),
            "missing_codes": list(missing),
            "requested_rows": 100,
            "observed_rows": len(source_rows),
            "missing_count": len(missing),
            "capture_after_target_cutoff": True,
            "temporal_cutoff_safe": False,
            "formal_stage_eligibility": "CANNOT_CONFIRM",
            "natural_time_capture": "CANNOT_CONFIRM",
            "pit_safe": False,
            "required_source_evidence_sha256": raw_store.canonical_sha(required_evidence),
        },
        "required_source_evidence": required_evidence,
        "safety": {
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    }
    token, manifest_marker, mode_marker = raw_store.historical_observation_manifest_markers(manifest)
    source_evidence = (
        *required_evidence,
        f"hk_d1_binding_sha256={pool_sha}",
        f"hk_d1_sha256={pool_sha}",
        f"hk_d1_source_trade_date={POOL_SOURCE_DATE}",
        f"hk_d1_source_signal_date={POOL_SIGNAL_DATE}",
        manifest_marker,
        mode_marker,
    )
    source = SourceResult(
        "pytdx_exhq",
        "PARTIAL_WITH_ROWS",
        rows=source_rows,
        cannot_confirm=cannot_confirm,
        requested_rows=100,
        missing_symbols=missing,
        source_evidence=source_evidence,
    )
    binding = StageUniverseBinding.ready(
        market="HK_CONNECT",
        trade_date=TRADE_DATE,
        role="HK_CONNECT_D1_TOP100",
        codes=codes,
        source_run_id="hk-d1-test-pool-run",
        sha256=pool_sha,
        evidence=(
            f"hk_d1_json={pool_path}",
            f"hk_d1_sha256={pool_sha}",
            "hk_d1_membership=exact_date_top100",
        ),
    )
    plan = SimpleNamespace(
        trade_date=TRADE_DATE,
        stage_id=STAGE_ID,
        codes_for=lambda market: codes if market == "HK_CONNECT" else (),
    )
    return {
        "codes": codes,
        "observed": observed,
        "missing": missing,
        "rows": source_rows,
        "manifest": manifest,
        "token": token,
        "evidence": source_evidence,
        "cannot_confirm": cannot_confirm,
        "source": source,
        "binding": binding,
        "plan": plan,
        "pool_path": pool_path,
    }


def _allows(case, *, trade_date=TRADE_DATE, source_evidence=None, token=_DEFAULT_TOKEN, source=None):
    source = source or case["source"]
    return raw_store._allows_temporal_false_observation(
        contract=case["token"] if token is _DEFAULT_TOKEN else token,
        trade_date=trade_date,
        stage_id=STAGE_ID,
        market="HK_CONNECT",
        source_id=source.source_id,
        source_status=source.status,
        rows=source.rows,
        requested_rows=source.requested_rows,
        missing_symbols=source.missing_symbols,
        cannot_confirm=source.cannot_confirm,
        source_evidence=case["evidence"] if source_evidence is None else source_evidence,
    )


def test_manifest_bound_partial_observation_publishes_and_verifies(tmp_path):
    case = _fixture_case(tmp_path)
    authorized, token = runner._authorize_manifest_bound_afterfact_observation(
        case["source"], case["plan"], binding=case["binding"],
        market="HK_CONNECT", historical_backfill=True, contract=case["token"],
    )
    assert token == case["token"]
    assert "hk_d1_source_trade_date=20260929" in authorized.source_evidence
    assert "hk_d1_source_signal_date=20260929" in authorized.source_evidence

    raw_source_evidence = tuple(dict.fromkeys((*authorized.source_evidence, *authorized.cannot_confirm)))
    projected_rows = tuple(
        {field: row[field] for field in raw_store.RAW_FIELDS}
        for row in authorized.rows
    )
    root = tmp_path / "raw-store"
    published = raw_store.RawStore(root).publish(
        trade_date=TRADE_DATE,
        stage_id=STAGE_ID,
        market="HK_CONNECT",
        source_id=authorized.source_id,
        source_status=authorized.status,
        rows=projected_rows,
        cannot_confirm=authorized.cannot_confirm,
        source_evidence=raw_source_evidence,
        requested_rows=authorized.requested_rows,
        missing_symbols=authorized.missing_symbols,
        window="09:30-09:35",
        cutoff_at="09:35",
        research_observation_contract=token,
    )
    verified = raw_store.RawStore(root).verify_latest(TRADE_DATE, STAGE_ID, "HK_CONNECT")
    assert published["status"] == "PARTIAL_WITH_ROWS"
    assert published["row_count"] == 75
    assert verified["verified"]["artifact_sha256"] == case["manifest"]["observation"]["raw_artifact_sha256"]
    assert verified["verified"]["status"] == "PARTIAL_WITH_ROWS"

    stored_manifest = json.loads((root / published["manifest_relative"]).read_text(encoding="utf-8"))
    selection_source = runner._attach_hk_authority(
        replace(authorized, source_evidence=raw_source_evidence),
        d1_root=tmp_path,
        second_root=None,
        preselection_source_root=None,
        trade_date=TRADE_DATE,
        stage_id=STAGE_ID,
        hk_binding=None,
    )
    assert selection_source.rows[0]["name"] == f"D1 name {selection_source.rows[0]['code']}"
    raw = {
        "trade_date": TRADE_DATE,
        "stage_id": STAGE_ID,
        "market": "HK_CONNECT",
        "source_id": "pytdx_exhq",
        "status": "PARTIAL_WITH_ROWS",
        "requested_rows": 100,
        "missing_symbols": list(case["missing"]),
        "cannot_confirm": stored_manifest["cannot_confirm"],
        "artifact_sha256": published["artifact_sha256"],
        "source_evidence": stored_manifest["source_evidence"],
        "cutoff_at": "09:35",
    }
    builder = production_selection_builders(STAGE_ID)["HK_CONNECT"]
    envelope = builder(selection_source, case["plan"], raw)
    assert envelope["selection_status"] == "PARTIAL_WITH_ROWS"
    assert envelope["requested_rows"] == 100
    assert envelope["source_rows"] == 75
    assert len(envelope["rows"]) == 10
    assert envelope["selection_mode"] == "RESEARCH_ONLY"
    assert envelope["observation_status"] == "OBSERVATION_UNVERIFIED"
    assert all(row["action_level"] == "NO_BUY" for row in envelope["rows"])
    assert all(row["status"] == "WATCH_ONLY" for row in envelope["rows"])
    assert all(row["formal_eligible"] is False for row in envelope["rows"])
    assert all(not row["candidate_lanes"] for row in envelope["rows"])
    assert envelope["production_allowed"] is False
    assert envelope["buy_gate_updated"] is False
    assert envelope["orders_sent"] is False
    selection_store = SelectionStore(tmp_path / "selection-store")
    selection_store.publish(envelope, market="HK_CONNECT")
    selection_readback = selection_store.read_verified(
        TRADE_DATE, STAGE_ID, "HK_CONNECT"
    )
    assert selection_readback["run_id"] == envelope["run_id"]
    assert selection_readback["selection_status"] == "PARTIAL_WITH_ROWS"

    # Runner authority may attach only the verified D1 fields after raw
    # publication.  A dynamic acquisition lane is not an after-fact D1 lane
    # and must fail closed at the selection boundary.
    spoofed_rows = list(selection_source.rows)
    spoofed_rows[0] = {**spoofed_rows[0], "candidate_lanes": ["LIVE_HKCONNECT_GAINER"]}
    spoofed = replace(selection_source, rows=tuple(spoofed_rows))
    rejected = builder(spoofed, case["plan"], raw)
    assert rejected["selection_status"] == "CANNOT_CONFIRM"
    assert "HISTORICAL_OBSERVATION_CANDIDATE_LANE_PRESENT" in rejected["cannot_confirm"]

    wrong_raw = {**raw, "artifact_sha256": "e" * 64}
    rejected_raw = builder(selection_source, case["plan"], wrong_raw)
    assert rejected_raw["selection_status"] == "CANNOT_CONFIRM"
    assert "HISTORICAL_OBSERVATION_ROW_OR_LINEAGE_CONTRACT_MISMATCH" in rejected_raw["cannot_confirm"]


def test_manifest_bound_false_observation_rejects_identity_or_lineage_drift(tmp_path):
    case = _fixture_case(tmp_path)
    assert _allows(case)
    assert not _allows(case, trade_date="20261001")
    assert not _allows(case, token=None)

    pool_drift = tuple(
        f"hk_d1_binding_sha256={'c' * 64}" if item.startswith("hk_d1_binding_sha256=") else item
        for item in case["evidence"]
    )
    assert not _allows(case, source_evidence=pool_drift)

    raw_sha_manifest = json.loads(json.dumps(case["manifest"]))
    raw_sha_manifest["observation"]["raw_artifact_sha256"] = "d" * 64
    _, raw_sha_marker, raw_sha_mode = raw_store.historical_observation_manifest_markers(raw_sha_manifest)
    raw_sha_evidence = tuple(
        item for item in case["evidence"]
        if not item.startswith((raw_store.HISTORICAL_OBSERVATION_MANIFEST_EVIDENCE_PREFIX,
                                raw_store.HISTORICAL_OBSERVATION_MODE_EVIDENCE_PREFIX))
    ) + (raw_sha_marker, raw_sha_mode)
    assert not _allows(case, source_evidence=raw_sha_evidence)

    missing_manifest = json.loads(json.dumps(case["manifest"]))
    missing_manifest["observation"]["missing_count"] -= 1
    missing_token, missing_marker, missing_mode = raw_store.historical_observation_manifest_markers(missing_manifest)
    missing_evidence = tuple(
        item for item in case["evidence"]
        if not item.startswith((raw_store.HISTORICAL_OBSERVATION_MANIFEST_EVIDENCE_PREFIX,
                                raw_store.HISTORICAL_OBSERVATION_MODE_EVIDENCE_PREFIX))
    ) + (missing_marker, missing_mode)
    assert not _allows(case, source_evidence=missing_evidence, token=missing_token)

    # Keep the manifest, required-evidence digest, and evidence markers
    # internally consistent while changing only the claimed close date.
    # The calendar-bound contract must still reject the prior open-session
    # mismatch for the 2026-09-30 target.
    wrong_price_manifest = json.loads(json.dumps(case["manifest"]))
    wrong_price_manifest["observation"]["price_signal_date"] = "20260928"
    wrong_required = sorted({
        item for item in wrong_price_manifest["required_source_evidence"]
        if not item.startswith("historical_price_signal_date=")
    } | {"historical_price_signal_date=20260928"})
    wrong_price_manifest["required_source_evidence"] = wrong_required
    wrong_price_manifest["observation"]["required_source_evidence_sha256"] = (
        raw_store.canonical_sha(wrong_required)
    )
    wrong_price_token, wrong_price_marker, wrong_price_mode = (
        raw_store.historical_observation_manifest_markers(wrong_price_manifest)
    )
    wrong_price_evidence = tuple(
        item for item in case["evidence"]
        if not item.startswith((
            "historical_price_signal_date=",
            raw_store.HISTORICAL_OBSERVATION_MANIFEST_EVIDENCE_PREFIX,
            raw_store.HISTORICAL_OBSERVATION_MODE_EVIDENCE_PREFIX,
        ))
    ) + tuple(wrong_required) + (wrong_price_marker, wrong_price_mode)
    assert not _allows(
        case, source_evidence=wrong_price_evidence, token=wrong_price_token
    )


def test_runner_rejects_generic_contract_without_exact_d1_binding(tmp_path):
    case = _fixture_case(tmp_path)
    bad_binding = replace(case["binding"], sha256="c" * 64)
    with pytest.raises(runner.RunnerError, match="full D1 artifact identity"):
        runner._authorize_manifest_bound_afterfact_observation(
            case["source"], case["plan"], binding=bad_binding,
            market="HK_CONNECT", historical_backfill=True, contract=case["token"],
        )


def test_afterfact_closed_connect_uses_exact_target_split_date_pool(monkeypatch, tmp_path):
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    from stage_center.calendar import TradingDayState

    target_date = "20261005"
    target_signal = "20261002"
    connect_eligibility_date = "20260930"
    target_codes = tuple(f"HK.{10_000 + index:05d}" for index in range(100))
    prior_codes = tuple(
        sorted(
            (*target_codes[:82], *(f"HK.{11_000 + index:05d}" for index in range(17)), "HK.02476")
        )
    )

    def states(trade_date):
        if trade_date in {target_date, target_signal}:
            return {
                "a_share": TradingDayState.NON_TRADING_DAY,
                "hk_securities": TradingDayState.FULL_TRADING_DAY,
                "hk_connect": TradingDayState.NON_TRADING_DAY,
            }
        if trade_date == connect_eligibility_date:
            return {
                "a_share": TradingDayState.NON_TRADING_DAY,
                "hk_securities": TradingDayState.FULL_TRADING_DAY,
                "hk_connect": TradingDayState.FULL_TRADING_DAY,
            }
        if trade_date == "20260929":
            return {
                "a_share": TradingDayState.NON_TRADING_DAY,
                "hk_securities": TradingDayState.FULL_TRADING_DAY,
                "hk_connect": TradingDayState.FULL_TRADING_DAY,
            }
        return {
            "a_share": TradingDayState.NON_TRADING_DAY,
            "hk_securities": TradingDayState.NON_TRADING_DAY,
            "hk_connect": TradingDayState.NON_TRADING_DAY,
        }

    def pool_payload(trade_date, signal_date, codes, *, provenance=None):
        source_run_id = f"synthetic-{trade_date}-{signal_date}"
        payload = {
            "schema_version": "v3_5.preselection_pool.v1",
            "trade_date": trade_date,
            "target_date": trade_date,
            "signal_date": signal_date,
            "pool_id": "hkconnect_d1_top100",
            "display_name": "HK Connect D-1 Top100",
            "market": "HK",
            "status": "STRICT_0_2_READY",
            "producer_id": "v3_shared_hk_0_2_consumer_v1",
            "source_role": "SHARED_VERIFIED_HK_0_2",
            "source_path": "read-only-test-fixture",
            "source_sha256": (
                provenance.get("d1_source_artifact_sha256", "a" * 64)
                if provenance is not None
                else "a" * 64
            ),
            "source_manifest_sha256": (
                provenance.get("d1_source_manifest_sha256", "b" * 64)
                if provenance is not None
                else "b" * 64
            ),
            "source_receipt_sha256": (
                provenance.get("d1_source_receipt_sha256", "c" * 64)
                if provenance is not None
                else "c" * 64
            ),
            "source_run_id": (
                provenance.get("d1_source_run_id", source_run_id)
                if provenance is not None
                else source_run_id
            ),
            "stage_selection_eligible": True,
            "rows": [
                {
                    "market": "HK",
                    "pool_id": "hkconnect_d1_top100",
                    "pool_rank": rank,
                    "signal_date": signal_date,
                    "code": code,
                    "symbol": code,
                    "target_date": trade_date,
                    "name": code,
                }
                for rank, code in enumerate(codes, start=1)
            ],
            "cannot_confirm": [],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        if provenance is not None:
            payload["historical_provenance"] = provenance
        return payload

    target_run_id = "synthetic-hk-d1-20261005-20261002"
    target_source_sha = "d" * 64
    target_manifest_sha = "e" * 64
    target_receipt_sha = "f" * 64
    target_provenance = {
        "schema_version": "v4.hk_d1_split_date_provenance.v1",
        "price_signal_date": target_signal,
        "eligibility_source_date": connect_eligibility_date,
        "eligibility_source_run_id": "synthetic-hk-connect-eligibility-20260930",
        "eligibility_source_artifact_sha256": "1" * 64,
        "d1_source_run_id": target_run_id,
        "d1_source_artifact_sha256": target_source_sha,
        "d1_source_manifest_sha256": target_manifest_sha,
        "d1_source_receipt_sha256": target_receipt_sha,
        "eligibility_source_captured_at": "2026-09-30T17:20:08+08:00",
    }

    monkeypatch.setattr(runner, "resolve_market_states", states)
    store = PreselectionPoolStore(tmp_path)
    store.materialize(
        pool_payload(connect_eligibility_date, "20260929", prior_codes)
    )
    store.materialize(
        pool_payload(
            target_date,
            target_signal,
            target_codes,
            provenance=target_provenance,
        )
    )

    # A verified target-date pool is preferred as a research observation when
    # HK securities are open and Connect is closed, without opening Connect.
    ordinary_binding = runner._build_hk_stage_binding(
        tmp_path, target_date, preselection_source_root=tmp_path
    )
    prior_snapshot = store.read_pool_snapshot(
        connect_eligibility_date, "hkconnect_d1_top100"
    )
    target_snapshot = store.read_pool_snapshot(target_date, "hkconnect_d1_top100")
    assert ordinary_binding.role == "HK_CONNECT_D1_TOP100"
    assert ordinary_binding.sha256 == target_snapshot["artifact_raw_sha256"]
    assert set(ordinary_binding.codes) == set(target_codes)
    assert "HK.02476" not in ordinary_binding.codes
    assert "hk_d1_binding_mode=EXACT_TARGET_DATE_RESEARCH_OBSERVATION" in ordinary_binding.evidence
    assert "hk_observation_mode=HK_SECURITIES_OPEN_HK_CONNECT_CLOSED" in ordinary_binding.evidence
    assert "hk_observation_scope=RESEARCH_ONLY" in ordinary_binding.evidence
    assert "production_allowed=false" in ordinary_binding.evidence
    assert "buy_gate_updated=false" in ordinary_binding.evidence
    assert "orders_sent=false" in ordinary_binding.evidence

    # A manifest-bound after-fact stage must use the exact target artifact,
    # whose split-date provenance was checked by the existing D1 validator.
    contract = runner.HISTORICAL_OBSERVATION_CONTRACT_PREFIX + ("a" * 64)
    context_token = runner._HK_TDX_AFTERFACT_RESEARCH_CONTRACT.set(contract)
    try:
        target_binding = runner._build_hk_stage_binding(
            tmp_path, target_date, preselection_source_root=tmp_path
        )
    finally:
        runner._HK_TDX_AFTERFACT_RESEARCH_CONTRACT.reset(context_token)

    assert target_binding.role == "HK_CONNECT_D1_TOP100"
    assert target_binding.sha256 == target_snapshot["artifact_raw_sha256"]
    assert set(target_binding.codes) == set(target_codes)
    assert "HK.02476" not in target_binding.codes
    assert (
        "hk_d1_binding_mode=MANIFEST_BOUND_AFTERFACT_EXACT_TARGET_DATE"
        in target_binding.evidence
    )


def test_afterfact_closed_connect_rejects_invalid_target_pool_without_prior_fallback(
    monkeypatch, tmp_path
):
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    from stage_center.calendar import TradingDayState

    target_date = "20261005"
    target_signal = "20261002"
    eligibility_date = "20260930"
    codes = tuple(f"HK.{10_000 + index:05d}" for index in range(100))

    def states(trade_date):
        if trade_date in {target_date, target_signal}:
            return {
                "a_share": TradingDayState.NON_TRADING_DAY,
                "hk_securities": TradingDayState.FULL_TRADING_DAY,
                "hk_connect": TradingDayState.NON_TRADING_DAY,
            }
        if trade_date in {eligibility_date, "20260929"}:
            return {
                "a_share": TradingDayState.NON_TRADING_DAY,
                "hk_securities": TradingDayState.FULL_TRADING_DAY,
                "hk_connect": TradingDayState.FULL_TRADING_DAY,
            }
        return {
            "a_share": TradingDayState.NON_TRADING_DAY,
            "hk_securities": TradingDayState.NON_TRADING_DAY,
            "hk_connect": TradingDayState.NON_TRADING_DAY,
        }

    monkeypatch.setattr(runner, "resolve_market_states", states)
    store = PreselectionPoolStore(tmp_path)
    store.materialize(
        {
            "schema_version": "v3_5.preselection_pool.v1",
            "trade_date": eligibility_date,
            "target_date": eligibility_date,
            "signal_date": "20260929",
            "pool_id": "hkconnect_d1_top100",
            "display_name": "HK Connect D-1 Top100",
            "market": "HK",
            "status": "STRICT_0_2_READY",
            "producer_id": "v3_shared_hk_0_2_consumer_v1",
            "source_role": "SHARED_VERIFIED_HK_0_2",
            "source_path": "read-only-test-fixture",
            "source_sha256": "a" * 64,
            "source_manifest_sha256": "b" * 64,
            "source_receipt_sha256": "c" * 64,
            "source_run_id": "synthetic-eligibility-source",
            "stage_selection_eligible": True,
            "rows": [
                {
                    "market": "HK",
                    "pool_id": "hkconnect_d1_top100",
                    "pool_rank": rank,
                    "signal_date": "20260929",
                    "code": code,
                    "symbol": code,
                    "target_date": eligibility_date,
                }
                for rank, code in enumerate(codes, start=1)
            ],
            "cannot_confirm": [],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    )
    # The exact target exists physically but fails the split-date signal
    # validation. An older valid Connect pool must not be substituted.
    store.materialize(
        {
            "schema_version": "v3_5.preselection_pool.v1",
            "trade_date": target_date,
            "target_date": target_date,
            "signal_date": target_signal,
            "pool_id": "hkconnect_d1_top100",
            "display_name": "HK Connect D-1 Top100",
            "market": "HK",
            "status": "STRICT_0_2_READY",
            "producer_id": "v3_shared_hk_0_2_consumer_v1",
            "source_role": "SHARED_VERIFIED_HK_0_2",
            "source_path": "read-only-test-fixture",
            "source_sha256": "d" * 64,
            "source_manifest_sha256": "e" * 64,
            "source_receipt_sha256": "f" * 64,
            "source_run_id": "synthetic-wrong-target-pool",
            "stage_selection_eligible": True,
            "historical_provenance": {
                "schema_version": "v4.hk_d1_split_date_provenance.v1",
                "price_signal_date": "20260929",
                "eligibility_source_date": eligibility_date,
                "eligibility_source_run_id": "synthetic-eligibility-source",
                "eligibility_source_artifact_sha256": "1" * 64,
                "d1_source_run_id": "synthetic-wrong-target-pool",
                "d1_source_artifact_sha256": "d" * 64,
                "d1_source_manifest_sha256": "e" * 64,
                "d1_source_receipt_sha256": "f" * 64,
                "eligibility_source_captured_at": "2026-09-30T17:20:08+08:00",
            },
            "rows": [
                {
                    "market": "HK",
                    "pool_id": "hkconnect_d1_top100",
                    "pool_rank": rank,
                    "signal_date": target_signal,
                    "code": code,
                    "symbol": code,
                    "target_date": target_date,
                }
                for rank, code in enumerate(codes, start=1)
            ],
            "cannot_confirm": [],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    )
    contract = runner.HISTORICAL_OBSERVATION_CONTRACT_PREFIX + ("b" * 64)
    context_token = runner._HK_TDX_AFTERFACT_RESEARCH_CONTRACT.set(contract)
    try:
        with pytest.raises(runner.RunnerError, match="split-date"):
            runner._build_hk_stage_binding(
                tmp_path, target_date, preselection_source_root=tmp_path
            )
    finally:
        runner._HK_TDX_AFTERFACT_RESEARCH_CONTRACT.reset(context_token)
