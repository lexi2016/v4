"""Synthetic R2/source binding checks. No feeds, model assets or network."""
from dataclasses import replace
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from research.p515_prospective_readiness import r2_resume as r2, wiring
from research.p515_prospective_readiness.coordinator import DailyPoolInput, PoolRow, canonical_matrix_and_keys
from research.p515_prospective_readiness.drive_store import sha256_bytes


def payload(value):
    return json.dumps(value, allow_nan=False).encode()


def make_case():
    D = "20261127"
    days = tuple((date(2026, 10, 26) + timedelta(days=i)).strftime("%Y%m%d")
                 for i in range(33) if (date(2026, 10, 26) + timedelta(days=i)).weekday() < 5)
    assert days[20] == "20261123" and days[-1] == D
    code = "699999.SH"
    all_codes = (code,) + tuple(f"{i:06d}.SZ" for i in range(1, 200))
    bars = [dict(ts_code=code, trade_date=d, open=10, high=10.2, low=9.8, close=10, volume=100)
            for d in days]
    bars[20].update(open=10.1, high=10.8, low=10, close=10.5, volume=200)
    bars[21].update(open=10.5, high=11.2, low=10.4, close=10.9, volume=100)
    bars[22].update(open=10.8, high=11, low=10.3, close=10.6, volume=80)
    bars[23].update(open=10.5, high=10.7, low=10.2, close=10.4, volume=70)
    bars[24].update(open=10.4, high=10.5, low=10.1, close=10.3, volume=60)
    top = payload(dict(schema="V4_A_SHARE_TOP200_V1", data_date=D, status="PARTIAL_DESCRIPTIVE",
                       top200_count=200, source_generation="1" * 64, input_sha256="2" * 64,
                       numeric_manifest={"sha256": "3" * 64}, artifact={"sha256": "4" * 64},
                       top200=[dict(symbol=c, rank=i, source_date="2026-11-27",
                                    **{k: bars[-1][k] for k in ("open", "high", "low", "close")})
                               for i, c in enumerate(all_codes, 1)]))
    identity = dict(generation="1" * 64, market="A", price_basis="QFQ_ASOF",
                    volume_basis="QFQ_EVENT_VOLUME", adjustment_snapshot_sha256="5" * 64,
                    panel_manifest_sha256="6" * 64, input_sha256="2" * 64, reader_sha256="7" * 64)
    reader = payload(dict(identity, format="P515_D_ONLY_READER_PROJECTION_V1", D=D,
                          price_adjustment_asof=D,
                          query=dict(start=days[0], end=D, ts_codes=all_codes,
                                     columns=list(bars[-1])), rows=bars))
    metadata = dict(identity, top200_raw_sha256=sha256_bytes(top),
                    top200_numeric_manifest_sha256="3" * 64, top200_artifact_sha256="4" * 64,
                    reader_projection_sha256=sha256_bytes(reader), top200_code_sha256="8" * 64)
    auth = "9" * 64
    receipt = payload(dict(schema=r2.ANCHOR_SCHEMA, anchor_kind="LISTING_INCEPTION", symbol=code,
                           boundary_date=days[0], boundary_basis="VERIFIED_LISTING_INCEPTION",
                           rule_source_sha256=r2.ORIGINAL_SOURCE_SHA256,
                           calendar_sha256=r2.calendar_identity_sha256(days),
                           source_identity_sha256=r2.source_identity_fingerprint(identity),
                           boundary_state_sha256=r2.listing_initial_state_sha256(code, days, identity),
                           authorization_receipt_sha256=auth, verified_by="synthetic",
                           verification_method="SYNTHETIC_FIXTURE_ONLY", verification_id="fixture-1",
                           verified_at="2026-11-18T12:00:00Z"))
    grant = r2.R2AnchorGrant(sha256_bytes(receipt), "synthetic", "SYNTHETIC_FIXTURE_ONLY", auth)
    anchor = wiring.AnchorEvidence(receipt, grant)
    features = (0, 1, 5, (10.6 - 11.2) / 11.2, (10.4 - 11.2) / 11.2, (10.3 - 11.2) / 11.2,
                (10.3 - 11.2) / 11.2, (10.2 - 11.2) / 11.2, (10.1 - 11.2) / 11.2,
                80 / 150, 70 / 150, 60 / 150, 60 / 112.5, 2, (10.3 - 10) / 10,
                0, 0, 0, 0, 1)
    instruments = {c: (c[-2:], "COMMON_A") for c in all_codes}
    bound = wiring.BoundV4Inputs(metadata=metadata, projection_sessions=days, r2_calendar=days,
                                anchors={code: anchor}, source_observed_at=datetime(
                                    2026, 11, 27, 18, tzinfo=ZoneInfo("Asia/Shanghai")),
                                instruments=instruments)
    row = PoolRow(1, code, "SH", "COMMON_A", "2026-11-27",
                  tuple(bars[-1][key] for key in wiring._BAR), features, bar_trade_date="2026-11-27")
    rows = (row,) + tuple(PoolRow(i, c, "SZ", "COMMON_A", "2026-11-27", None, None)
                          for i, c in enumerate(all_codes[1:], 2))
    daily = DailyPoolInput("2026-11-27", bound.source_observed_at, top, rows, reader,
                           identity["generation"], identity["panel_manifest_sha256"],
                           identity["input_sha256"], synthetic_fixture=True)
    return bound, daily, row, identity, bars


def test_top200_reader_and_r2_share_same_pinned_bytes():
    bound, daily, row, identity, bars = make_case()
    hashes = canonical_matrix_and_keys(daily.rows)[1:]
    source = wiring.BoundSourceVerifier(bound).verify(daily, *hashes)
    assert source.top200_roster[0] == (1, row.ts_code, daily.D)
    proofs, evidence = wiring.BoundStateVerifier(bound).verify(daily, (row,), None)
    proved = proofs[row.ts_code]
    assert sha256_bytes(evidence[row.ts_code].checkpoint_bytes) == proved.checkpoint_sha256
    assert proved.pb_id == f"P5146_EVENT_RULE_R2:{row.ts_code}:20261123:PB1"
    assert proved.pullback_sessions == 3 and proved.terminal_on_D is False
    seed = bound.anchors[row.ts_code]
    session = r2.R2Session.from_listing_inception(
        symbol=row.ts_code, calendar=bound.r2_calendar, source_identity=identity,
        receipt_bytes=seed.receipt, grant=seed.grant,
    )
    session.feed(bars[:-1], source_identity=identity)
    snap = session.snapshot()
    bound.anchors[row.ts_code] = replace(seed, checkpoint=snap, checkpoint_sha256=sha256_bytes(snap))
    assert bound.state_proofs(daily, (row,))[row.ts_code] == proved


def test_unknown_anchor_fails_closed_and_input_fabrication_is_rejected():
    bound, daily, row, _, _ = make_case()
    invented = replace(row, bar_values=(1, 2, 1, 2, 1000))
    bad_daily = replace(daily, rows=(invented, *daily.rows[1:]))
    with pytest.raises(ValueError, match="BAR_DIFFERS"):
        bound.source_proof(bad_daily, *canonical_matrix_and_keys(bad_daily.rows)[1:])
    fake_features = replace(row, features=(0,) * 20)
    with pytest.raises(ValueError, match="FEATURES_DIFFER"):
        bound.state_proofs(daily, (fake_features,))
    bound.anchors.clear()
    assert bound.state_proofs(daily, (row,))[row.ts_code].status == "UNKNOWN"


def test_anchor_catalog_does_not_admit_the_fixture_grant():
    bound, daily, row, _, _ = make_case()
    candidate = replace(daily, synthetic_fixture=False)
    with pytest.raises(ValueError, match="CATALOG_NOT_BOUND"):
        bound.state_proofs(candidate, (row,))
    evidence = bound.anchors[row.ts_code]
    certificate = json.loads(evidence.receipt)
    bound.anchor_catalog_bytes = payload({
        "schema": "P515_VERIFIED_R2_ANCHOR_CATALOG_V1",
        "securities": {row.ts_code: [{
            "receipt_sha256": evidence.grant.pinned_receipt_sha256,
            "incoming_checkpoint_sha256": None,
            "boundary_date": certificate["boundary_date"],
            "verification_method": evidence.grant.verification_method,
            "verification_id": certificate["verification_id"],
            "verifier_id": evidence.grant.verifier_id,
            "authorization_receipt_sha256": evidence.grant.authorization_receipt_sha256,
        }]},
    })
    pins = SimpleNamespace(identity_sha256={"r2_anchor_catalog_sha256": sha256_bytes(
        bound.anchor_catalog_bytes
    )})
    assert bound.state_proofs(candidate, (row,), pins)[row.ts_code].status == "UNKNOWN"


def test_coordinator_reads_bound_source_and_r2_fixture(tmp_path):
    from research.p515_prospective_readiness.coordinator import ReadinessCoordinator

    bound, daily, _, _, _ = make_case()
    runner = ReadinessCoordinator(
        tmp_path, source_verifier=wiring.BoundSourceVerifier(bound),
        state_verifier=wiring.BoundStateVerifier(bound), fixture_only=True,
        clock=lambda: daily.captured_at,
    )
    prepared = runner.prepare_day(daily)
    assert sum(item.disposition == "ELIGIBLE" for item in prepared.dispositions) == 1
    assert len(prepared.dispositions) == 200
    assert prepared.dispositions[0].pb_id.endswith(":20261123:PB1")
    assert prepared.paired_output_rows == 2  # reservation only; no outputs generated


def test_empty_coordinator_fixture_only_returns_an_opaque_marker(tmp_path):
    from research.p515_prospective_readiness.coordinator import (
        FIXTURE_AUTHORIZATION_BYTES, FIXTURE_ID, NoGoError, ReadinessCoordinator,
    )

    bound, daily, _, _, _ = make_case()
    bound.anchors.clear()
    daily = replace(daily, rows=tuple(replace(row, features=None) for row in daily.rows))
    runner = ReadinessCoordinator(
        tmp_path, source_verifier=wiring.BoundSourceVerifier(bound),
        state_verifier=wiring.BoundStateVerifier(bound), fixture_only=True, clock=lambda: daily.captured_at,
    )
    prepared = runner.prepare_day(daily)
    hits = []

    def placeholder(invocation):
        hits.append(invocation.marker)
        return {"fixture_id": FIXTURE_ID, "status": "PLACEHOLDER_ONLY", "probability_rows": 0}

    with pytest.raises(NoGoError):
        runner.execute_fixture_placeholder(prepared, authorization_bytes=b"", callback=placeholder)
    assert not hits
    result = runner.execute_fixture_placeholder(
        prepared, authorization_bytes=FIXTURE_AUTHORIZATION_BYTES, callback=placeholder,
    )
    assert result == "PLACEHOLDER_CALLBACK_PASS__MODEL_API_0__PROBABILITIES_0"
    assert hits == ["NO_MARKET_NO_MODEL_NO_PROBABILITY"]
    assert prepared.dispositions[0].disposition == "STATE_ANCHOR_UNKNOWN"
    assert prepared.paired_output_rows == 0
    text = Path(runner.study_root / "EXECUTION.jsonl").read_text()
    assert "MODEL_CALL_START" not in text
