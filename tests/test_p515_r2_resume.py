from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json

import pytest

from research.p515_prospective_readiness import r2_resume as r2


IDENTITY = {
    "generation": "synthetic-generation-01",
    "market": "A",
    "price_basis": "QFQ_ASOF",
    "volume_basis": "QFQ_EVENT_VOLUME",
}
SYMBOL = "600001.SH"
AUTH_SHA = hashlib.sha256(b"synthetic authorization record").hexdigest()
VERIFIER_ID = "synthetic-independent-verifier"
METHOD = "SYNTHETIC_FIXTURE_ONLY"


def _calendar(n: int) -> list[str]:
    start = date(2026, 1, 5)
    return [(start + timedelta(days=index)).strftime("%Y%m%d") for index in range(n)]


def _receipt(kind: str, boundary_date: str, boundary_state_sha256: str,
             calendar: list[str], *, basis: str | None = None,
             reset_reason: str | None = None, no_feed_gap_substitution: bool | None = None,
             identity: dict[str, str] = IDENTITY, symbol: str = SYMBOL) -> tuple[bytes, r2.R2AnchorGrant]:
    value = {
        "schema": r2.ANCHOR_SCHEMA,
        "anchor_kind": kind,
        "symbol": symbol,
        "boundary_date": boundary_date,
        "boundary_basis": basis or ("VERIFIED_LISTING_INCEPTION" if kind == "LISTING_INCEPTION" else "VERIFIED_CLEAN_RULE_RESET"),
        "rule_source_sha256": r2.ORIGINAL_SOURCE_SHA256,
        "calendar_sha256": r2.calendar_identity_sha256(calendar),
        "source_identity_sha256": r2.source_identity_fingerprint(identity),
        "boundary_state_sha256": boundary_state_sha256,
        "authorization_receipt_sha256": AUTH_SHA,
        "verified_by": VERIFIER_ID,
        "verification_method": METHOD,
        "verification_id": "synthetic-verification-0001",
        "verified_at": "2026-11-18T12:00:00Z",
    }
    if kind == "PROVEN_CLEAN_RESET":
        value["reset_reason_code"] = reset_reason or "UPSTREAM_EXPLICIT_RESET"
        value["no_feed_gap_substitution"] = True if no_feed_gap_substitution is None else no_feed_gap_substitution
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    grant = r2.R2AnchorGrant(
        pinned_receipt_sha256=hashlib.sha256(payload).hexdigest(),
        verifier_id=VERIFIER_ID,
        verification_method=METHOD,
        authorization_receipt_sha256=AUTH_SHA,
    )
    return payload, grant


def _session(calendar: list[str], *, identity: dict[str, str] = IDENTITY,
             symbol: str = SYMBOL) -> tuple[r2.R2Session, bytes, r2.R2AnchorGrant]:
    init_hash = r2.listing_initial_state_sha256(symbol, calendar, identity)
    receipt, grant = _receipt("LISTING_INCEPTION", calendar[0], init_hash, calendar,
                             identity=identity, symbol=symbol)
    session = r2.R2Session.from_listing_inception(
        symbol=symbol, calendar=calendar, source_identity=identity,
        receipt_bytes=receipt, grant=grant,
    )
    return session, receipt, grant


def _bar(day: str, *, open_: float = 10.0, high: float = 10.2, low: float = 9.8,
         close: float = 10.0, volume: float = 100.0) -> dict[str, object]:
    return {"trade_date": day, "open": open_, "high": high, "low": low,
            "close": close, "volume": volume}


def _label_sequence(calendar: list[str]) -> list[dict[str, object]]:
    rows = [_bar(day) for day in calendar[:20]]
    rows.extend([
        _bar(calendar[20], open_=10.1, high=10.8, low=10.0, close=10.5, volume=200),  # family origin
        _bar(calendar[21], open_=10.5, high=11.2, low=10.4, close=10.9, volume=100),  # advance
        _bar(calendar[22], open_=10.8, high=11.0, low=10.3, close=10.6, volume=80),   # PB starts
        _bar(calendar[23], open_=10.5, high=10.7, low=10.2, close=10.4, volume=70),   # active PB
        _bar(calendar[24], open_=10.8, high=12.5, low=10.7, close=12.0, volume=110),  # restart
        _bar(calendar[25], open_=12.0, high=12.1, low=11.0, close=11.5, volume=200),  # FAILED_RISK
    ])
    return rows


def _feed(session: r2.R2Session, rows: list[dict[str, object]]) -> r2.R2Delta:
    return session.feed(rows, source_identity=IDENTITY)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_every_chunk_boundary_matches_original_four_streams_and_state() -> None:
    calendar = _calendar(40)
    rows = _label_sequence(calendar)
    expected = r2._run_original_for_equivalence(SYMBOL, rows, calendar)

    continuous, receipt, grant = _session(calendar)
    _feed(continuous, rows)
    uninterrupted_snapshot = continuous.snapshot()  # snapshot does not add an EOF UNKNOWN label
    assert continuous.current_event is None
    continuous.finalize()
    assert continuous.readout() == expected

    # Every cut includes warmup, origin, active mother/PB, terminal labels, and
    # cuts immediately before/after each transition. The input hash chain and
    # the full R2 state are chunk-boundary independent.
    for cut in range(1, len(rows)):
        first, _, first_grant = _session(calendar)
        _feed(first, rows[:cut])
        mid_snapshot = first.snapshot()
        resumed = r2.R2Session.resume(
            snapshot_bytes=mid_snapshot,
            pinned_snapshot_sha256=_sha(mid_snapshot),
            symbol=SYMBOL,
            calendar=calendar,
            source_identity=IDENTITY,
            receipt_bytes=receipt,
            grant=first_grant,
        )
        _feed(resumed, rows[cut:])
        assert resumed.snapshot() == uninterrupted_snapshot, f"state differs at cut={cut}"
        resumed.finalize()
        assert resumed.readout() == expected, f"four-stream mismatch at cut={cut}"


def test_snapshot_keeps_active_family_and_pb_open_until_explicit_readout() -> None:
    calendar = _calendar(32)
    rows = _label_sequence(calendar)
    session, _, _ = _session(calendar)
    _feed(session, rows[:24])
    assert session.current_event is not None
    assert session.current_event["pullback_id"] is not None
    before = session.readout()
    snapshot = session.snapshot()
    restored = r2.R2Session.resume(
        snapshot_bytes=snapshot,
        pinned_snapshot_sha256=_sha(snapshot),
        symbol=SYMBOL,
        calendar=calendar,
        source_identity=IDENTITY,
        receipt_bytes=_session(calendar)[1],
        grant=_session(calendar)[2],
    )
    assert restored.current_event is not None
    assert restored.current_event["pullback_id"] is not None
    assert restored.readout() == before
    assert not any(row.get("outcome") == "UNKNOWN_OPEN_AT_SNAPSHOT" for row in restored.readout()[3])
    restored.finalize()
    assert restored.current_event is None
    assert any(row.get("outcome") == "UNKNOWN_OPEN_AT_SNAPSHOT" for row in restored.readout()[3])


def test_warmup_prior_window_and_bad_bar_clear_are_fully_snapshotted() -> None:
    calendar = _calendar(30)
    session, receipt, grant = _session(calendar)
    _feed(session, [_bar(day) for day in calendar[:7]])
    assert len(session.prior_warmup_rows) == 7
    snapshot = session.snapshot()
    restored = r2.R2Session.resume(
        snapshot_bytes=snapshot, pinned_snapshot_sha256=_sha(snapshot),
        symbol=SYMBOL, calendar=calendar, source_identity=IDENTITY,
        receipt_bytes=receipt, grant=grant,
    )
    _feed(restored, [_bar(day) for day in calendar[7:20]])
    assert len(restored.prior_warmup_rows) == 20

    # Once a PB is active, a non-finite source value must take the original
    # UNKNOWN_BAD_BAR clearing path and remain serializable as a checkpoint.
    active_rows = _label_sequence(calendar)[20:23]
    _feed(restored, active_rows)
    assert restored.current_event is not None
    bad = _bar(calendar[23], open_=10.5, high=10.8, low=10.1, close=float("nan"), volume=90)
    delta = _feed(restored, [bad])
    assert restored.current_event is None
    assert delta.pullbacks[-1]["outcome"] == "UNKNOWN_BAD_BAR"
    assert restored.readout()[2][-1]["outcome"] == "UNKNOWN_BAD_BAR"
    decoded = json.loads(restored.snapshot().decode("utf-8"))
    assert decoded["schema"] == r2.SNAPSHOT_SCHEMA


def test_calendar_gap_clears_live_state_and_preserves_unknown_labels() -> None:
    calendar = _calendar(34)
    session, _, _ = _session(calendar)
    rows = _label_sequence(calendar)[:23]
    _feed(session, rows)
    assert session.current_event is not None
    # Omitting calendar[23] is an observed feed gap after the anchor; the
    # original rule must terminate as UNKNOWN and clear active state.
    gap_followup = _bar(calendar[24], open_=10.5, high=10.7, low=10.2, close=10.4, volume=70)
    delta = _feed(session, [gap_followup])
    assert session.current_event is None
    assert delta.pullbacks[-1]["outcome"] == "UNKNOWN_DATA_GAP"
    assert delta.completed[-1]["outcome"] == "UNKNOWN_DATA_GAP"
    assert session.prior_warmup_rows == [gap_followup]


def test_mature_pb_labels_preserve_original_success_risk_and_expiry_rules() -> None:
    calendar = _calendar(70)
    rows = _label_sequence(calendar)
    original = r2._run_original_for_equivalence(SYMBOL, rows, calendar)
    session, _, _ = _session(calendar)
    _feed(session, rows)
    session.finalize()
    assert session.readout() == original
    pullbacks = original[3]
    assert any(item["outcome"] == "SUCCESS_RESTART" and item["outcome_mature_at"] for item in pullbacks)
    assert original[2][-1]["outcome"] == "FAILED_RISK"
    assert original[2][-1]["outcome_mature_at"]

    # Build an active PB that reaches exactly 15 exchange sessions without a
    # restart, then verify the original EXPIRED_PULLBACK terminal label.
    expiry = [_bar(day) for day in calendar[:20]]
    expiry.extend([
        _bar(calendar[20], open_=10.1, high=10.8, low=10.0, close=10.5, volume=200),
        _bar(calendar[21], open_=10.5, high=11.2, low=10.4, close=10.9, volume=100),
        _bar(calendar[22], open_=10.8, high=11.0, low=10.3, close=10.6, volume=80),
    ])
    for index in range(23, 37):
        expiry.append(_bar(calendar[index], open_=10.6, high=10.8, low=10.1, close=10.4, volume=80))
    exp_original = r2._run_original_for_equivalence(SYMBOL, expiry, calendar)
    exp_session, _, _ = _session(calendar)
    _feed(exp_session, expiry)
    exp_session.finalize()
    assert exp_session.readout() == exp_original
    assert any(item["outcome"] == "EXPIRED_PULLBACK" for item in exp_original[3])


def test_proven_clean_reset_accepts_exact_pinned_state_and_keeps_completed_history() -> None:
    calendar = _calendar(40)
    source, _, _ = _session(calendar)
    _feed(source, _label_sequence(calendar))
    assert source.current_event is None
    assert source.readout()[2]
    assert source.readout()[3]
    envelope = json.loads(source.snapshot().decode("utf-8"))
    runtime = r2._unwire(envelope["runtime_state"])
    runtime["current"] = None
    runtime["prior"] = []
    runtime["prev_date"] = calendar[25]
    wire = r2._wire(runtime)
    envelope["runtime_state"] = wire
    envelope["runtime_state_sha256"] = _sha(json.dumps(wire, ensure_ascii=False, sort_keys=True,
                                                         separators=(",", ":")).encode("utf-8"))
    reset_snapshot = json.dumps(envelope, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")).encode("utf-8")
    reset_receipt, reset_grant = _receipt(
        "PROVEN_CLEAN_RESET", calendar[25], envelope["runtime_state_sha256"], calendar,
        basis="VERIFIED_CLEAN_RULE_RESET", reset_reason="UPSTREAM_EXPLICIT_RESET",
        no_feed_gap_substitution=True,
    )
    reset = r2.R2Session.from_proven_reset(
        snapshot_bytes=reset_snapshot, pinned_snapshot_sha256=_sha(reset_snapshot),
        symbol=SYMBOL, calendar=calendar, source_identity=IDENTITY,
        receipt_bytes=reset_receipt, grant=reset_grant,
    )
    assert reset.processed_rows == 26
    assert reset.prior_warmup_rows == []
    assert reset.readout() == source.readout()
    next_row = _bar(calendar[26])
    _feed(reset, [next_row])
    assert reset.processed_rows == 27


def test_rejects_unpinned_or_wrong_anchor_snapshot_identity_and_fake_reset() -> None:
    calendar = _calendar(30)
    session, receipt, grant = _session(calendar)
    _feed(session, [_bar(calendar[0])])
    snapshot = session.snapshot()

    with pytest.raises(r2.R2ResumeError, match="SNAPSHOT_SHA_MISMATCH"):
        r2.R2Session.resume(
            snapshot_bytes=snapshot, pinned_snapshot_sha256="0" * 64,
            symbol=SYMBOL, calendar=calendar, source_identity=IDENTITY,
            receipt_bytes=receipt, grant=grant,
        )
    with pytest.raises(r2.R2ResumeError, match="SNAPSHOT_SYMBOL_MISMATCH"):
        r2.R2Session.resume(
            snapshot_bytes=snapshot, pinned_snapshot_sha256=_sha(snapshot),
            symbol="600002.SH", calendar=calendar, source_identity=IDENTITY,
            receipt_bytes=receipt, grant=grant,
        )
    changed_identity = {**IDENTITY, "generation": "other-generation"}
    with pytest.raises(r2.R2ResumeError, match="SNAPSHOT_SOURCE_IDENTITY_MISMATCH"):
        r2.R2Session.resume(
            snapshot_bytes=snapshot, pinned_snapshot_sha256=_sha(snapshot),
            symbol=SYMBOL, calendar=calendar, source_identity=changed_identity,
            receipt_bytes=receipt, grant=grant,
        )
    with pytest.raises(r2.R2ResumeError, match="ANCHOR_RECEIPT_SHA_MISMATCH"):
        r2.R2Session.resume(
            snapshot_bytes=snapshot, pinned_snapshot_sha256=_sha(snapshot),
            symbol=SYMBOL, calendar=calendar, source_identity=IDENTITY,
            receipt_bytes=receipt + b" ", grant=grant,
        )

    tampered_envelope = json.loads(snapshot)
    tampered_runtime = r2._unwire(tampered_envelope["runtime_state"])
    tampered_runtime["prev_date"] = calendar[2]
    tampered_envelope["runtime_state"] = r2._wire(tampered_runtime)
    tampered_snapshot = json.dumps(tampered_envelope, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")).encode("utf-8")
    with pytest.raises(r2.R2ResumeError, match="SNAPSHOT_RUNTIME_STATE_SHA_MISMATCH"):
        r2.R2Session.resume(
            snapshot_bytes=tampered_snapshot, pinned_snapshot_sha256=_sha(tampered_snapshot),
            symbol=SYMBOL, calendar=calendar, source_identity=IDENTITY,
            receipt_bytes=receipt, grant=grant,
        )

    forged_receipt = json.loads(receipt)
    forged_receipt["boundary_basis"] = "FEED_GAP"
    forged_payload = json.dumps(forged_receipt, sort_keys=True, separators=(",", ":")).encode()
    forged_grant = r2.R2AnchorGrant(
        pinned_receipt_sha256=_sha(forged_payload), verifier_id=VERIFIER_ID,
        verification_method=METHOD, authorization_receipt_sha256=AUTH_SHA,
    )
    with pytest.raises(r2.R2ResumeError, match="LISTING_INCEPTION_BASIS_REQUIRED"):
        r2.R2Session.from_listing_inception(
            symbol=SYMBOL, calendar=calendar, source_identity=IDENTITY,
            receipt_bytes=forged_payload, grant=forged_grant,
        )

    reset_payload, reset_grant = _receipt(
        "PROVEN_CLEAN_RESET", calendar[0], "1" * 64, calendar,
        basis="DATA_GAP", reset_reason="MISSING_EXCHANGE_SESSION",
        no_feed_gap_substitution=False,
    )
    with pytest.raises(r2.R2ResumeError, match="CLEAN_RESET_BASIS_REQUIRED"):
        r2.R2Session.from_proven_reset(
            snapshot_bytes=snapshot, pinned_snapshot_sha256=_sha(snapshot),
            symbol=SYMBOL, calendar=calendar, source_identity=IDENTITY,
            receipt_bytes=reset_payload, grant=reset_grant,
        )


def test_rejects_changed_source_identity_between_chunks_without_mutating_state() -> None:
    calendar = _calendar(30)
    session, _, _ = _session(calendar)
    _feed(session, [_bar(calendar[0])])
    before = session.snapshot()
    with pytest.raises(r2.R2ResumeError, match="FEED_SOURCE_IDENTITY_CHANGED"):
        session.feed([_bar(calendar[1])], source_identity={**IDENTITY, "generation": "changed"})
    assert session.snapshot() == before
